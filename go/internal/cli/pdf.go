package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	"csb/internal/mdgen"
	"csb/internal/pdfgen"
	"csb/internal/store"
)

// cmdPDF generates a styled PDF from a stored item's Markdown (backlog #5).
//
// It (re)generates the Markdown from the stored JSON (the SSOT) so the PDF is
// always current, warns when an item isn't fully fetched (unless --force), and
// writes <name>.pdf next to the vault <name>.md. A path cascades to its courses
// and labs, mirroring `fetch` ("the item and any subitem").
func cmdPDF(args []string) int {
	p := parseArgs(args, map[string]bool{
		"-c": true, "--course": true,
		"-p": true, "--path": true,
		"-l": true, "--lab": true,
		"--theme": true,
	})

	if p.has("--list-themes") {
		return listThemes()
	}

	themeName, _ := p.value("--theme")
	theme, err := pdfgen.LoadTheme(themeName)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error loading theme: %v\n", err)
		return 1
	}

	// --doctor: report the pipeline's readiness and stop. --json is for the GUI.
	if p.has("--doctor") {
		return pdfDoctor(theme, p.has("--json"))
	}

	// Otherwise check readiness up front, so a missing tool produces the same
	// actionable checklist instead of pandoc/typst's bare "not found on PATH".
	// Missing FONTS only warn: the PDF still renders, just with typst's fallback
	// family, and the user may not care enough to stop the run over it.
	report := pdfgen.Doctor(theme)
	if missingTools(report) {
		fmt.Fprintf(os.Stderr, "Cannot generate PDFs yet — the toolchain is incomplete.\n\n")
		printDoctor(os.Stderr, report)
		return 1
	}
	warnMissingFonts(report)

	force := p.has("--force", "-f")
	opts := mdgen.Options{
		TOCOnly:      p.has("--toc", "-t"),
		NoTranscript: p.has("--md-no-transcript", "--no-transcript"),
	}

	courseIDs, hasC := p.value("-c", "--course")
	pathIDs, hasP := p.value("-p", "--path")
	labIDs, hasL := p.value("-l", "--lab")
	if !hasC && !hasP && !hasL {
		fmt.Println("Please specify at least one item type: --course, --path, or --lab.")
		return 1
	}

	fmt.Printf("Using theme '%s' [%s].\n", theme.Name, p.portal)
	rc := 0
	for _, id := range splitIDs(pathIDs) {
		if !generatePathPDF(p.portal, id, theme, opts, force) {
			rc = 1
		}
	}
	for _, id := range splitIDs(courseIDs) {
		if !generateItemPDF(p.portal, "courses", id, theme, opts, force, false) {
			rc = 1
		}
	}
	for _, id := range splitIDs(labIDs) {
		if !generateItemPDF(p.portal, "labs", id, theme, opts, force, false) {
			rc = 1
		}
	}
	return rc
}

// generateItemPDF (re)generates the item's Markdown then renders its PDF. When
// cascade is true (a path's child), a not-stored item is a soft skip rather than
// a failure, so a partly fetched path still produces PDFs for what it has.
func generateItemPDF(portalKey, table, id string, theme pdfgen.Theme, opts mdgen.Options, force, cascade bool) bool {
	kind := strings.TrimSuffix(table, "s") // courses -> course
	if !itemStored(portalKey, table, id) {
		if cascade {
			fmt.Printf("  · %s %s not fetched — skipping.\n", kind, id)
			return true
		}
		fmt.Printf("%s %s data not found. Please fetch it first.\n", capitalize(kind), id)
		return false
	}
	fmt.Printf("Generating %s %s PDF [%s]...\n", kind, id, portalKey)
	if !force && !itemComplete(portalKey, kind, id) {
		fmt.Printf("  ⚠ %s %s isn't fully fetched — the PDF may be incomplete (use --force to silence).\n", capitalize(kind), id)
	}
	mdPath, err := writeMarkdownFor(portalKey, table, id, opts)
	if err != nil {
		fmt.Fprintf(os.Stderr, "  error: %v\n", err)
		return false
	}
	pdfPath := pdfgen.PdfPathForMD(mdPath)
	if err := pdfgen.Render(mdPath, pdfPath, theme); err != nil {
		fmt.Fprintf(os.Stderr, "  error: %v\n", err)
		return false
	}
	fmt.Printf("PDF saved to %s\n", pdfPath)
	return true
}

// generatePathPDF renders the path's own PDF then cascades to its courses and
// labs (like fetch), so one command produces the whole set.
func generatePathPDF(portalKey, id string, theme pdfgen.Theme, opts mdgen.Options, force bool) bool {
	ok := generateItemPDF(portalKey, "paths", id, theme, opts, force, false)
	pth, err := store.LoadPath(portalKey, id)
	if err != nil || pth == nil {
		return ok
	}
	for _, key := range pth.Courses.Keys {
		ref := pth.Courses.Values[key]
		table := "courses"
		if strings.Contains(strings.ToLower(ref.Type), "lab") {
			table = "labs"
		}
		if !generateItemPDF(portalKey, table, ref.ID, theme, opts, force, true) {
			ok = false
		}
	}
	return ok
}

// writeMarkdownFor (re)generates and writes the item's vault Markdown from its
// stored JSON, returning the .md path. Mirrors the `md` command's per-type flow.
func writeMarkdownFor(portalKey, table, id string, opts mdgen.Options) (string, error) {
	switch table {
	case "courses":
		c, err := store.LoadCourse(portalKey, id)
		if err != nil {
			return "", err
		}
		if c == nil || c.Title == "" {
			return "", fmt.Errorf("course %s not stored", id)
		}
		return store.WriteCourseMarkdown(c, mdgen.Course(c, opts))
	case "paths":
		pth, err := store.LoadPath(portalKey, id)
		if err != nil {
			return "", err
		}
		if pth == nil || pth.Title == "" {
			return "", fmt.Errorf("path %s not stored", id)
		}
		return store.WritePathMarkdown(pth, mdgen.Path(pth, opts))
	case "labs":
		lab, err := store.LoadLab(portalKey, id)
		if err != nil {
			return "", err
		}
		if lab == nil || lab.Title == "" {
			return "", fmt.Errorf("lab %s not stored", id)
		}
		return store.WriteLabMarkdown(lab, mdgen.Lab(lab, opts))
	}
	return "", fmt.Errorf("unknown type %q", table)
}

// itemStored reports whether the item's JSON is present (has a usable record) —
// distinct from itemComplete, which also requires the whole cascade.
func itemStored(portalKey, table, id string) bool {
	switch table {
	case "courses":
		c, _ := store.LoadCourse(portalKey, id)
		return c != nil && c.Title != ""
	case "paths":
		p, _ := store.LoadPath(portalKey, id)
		return p != nil && p.Title != ""
	case "labs":
		l, _ := store.LoadLab(portalKey, id)
		return l != nil
	}
	return false
}

// missingTools reports whether any external program the pipeline needs is absent.
func missingTools(r pdfgen.Report) bool {
	for _, t := range r.Tools {
		if !t.Found {
			return true
		}
	}
	return false
}

// warnMissingFonts names the theme fonts typst will have to substitute. Worth its
// own warning because typst only mentions it mid-render and still exits 0, so the
// result is a PDF that looks wrong without anything having obviously failed.
func warnMissingFonts(r pdfgen.Report) {
	if !r.FontsChecked {
		return
	}
	var missing []string
	for _, f := range r.Fonts {
		if !f.Found {
			missing = append(missing, f.Family)
		}
	}
	if len(missing) == 0 {
		return
	}
	fmt.Fprintf(os.Stderr,
		"  ⚠ Missing font(s): %s — the PDF will use substitutes. Run `pdf --doctor` for install steps.\n",
		strings.Join(missing, ", "))
}

// pdfDoctor prints the readiness report — JSON for the GUI, a checklist for
// humans — and exits non-zero when something still needs installing, so it works
// in a shell conditional.
func pdfDoctor(theme pdfgen.Theme, asJSON bool) int {
	report := pdfgen.Doctor(theme)
	if asJSON {
		b, err := json.MarshalIndent(report, "", "  ")
		if err != nil {
			fmt.Fprintf(os.Stderr, "error encoding report: %v\n", err)
			return 1
		}
		fmt.Println(string(b))
	} else {
		printDoctor(os.Stdout, report)
	}
	if report.OK {
		return 0
	}
	return 1
}

// mark is the status glyph for one check.
func mark(ok bool) string {
	if ok {
		return "✓"
	}
	return "✗"
}

// printRow writes one "  <glyph> <name padded> <detail>" checklist line, padding
// the name only when a detail follows so no line ends in whitespace.
func printRow(w io.Writer, glyph, name string, pad int, detail string) {
	if detail == "" {
		fmt.Fprintf(w, "  %s %s\n", glyph, name)
		return
	}
	fmt.Fprintf(w, "  %s %-*s %s\n", glyph, pad, name, detail)
}

// printDoctor writes the human-readable readiness checklist: what is present,
// what is missing, and the exact command or link that fixes each gap.
func printDoctor(w io.Writer, r pdfgen.Report) {
	fmt.Fprintf(w, "PDF setup — theme '%s' on %s\n\n", r.Theme, r.OS)

	fmt.Fprintln(w, "Tools")
	for _, t := range r.Tools {
		detail := ""
		switch {
		case t.Found && t.Version != "":
			detail = t.Version
		case t.Install != "":
			detail = "install with:  " + t.Install
		case t.URL != "":
			detail = "get it from:  " + t.URL
		}
		printRow(w, mark(t.Found), t.Name, 7, detail)
	}

	if len(r.Fonts) > 0 {
		fmt.Fprint(w, "\nFonts")
		if r.FontDir != "" {
			fmt.Fprintf(w, "  (install to %s)", r.FontDir)
		}
		fmt.Fprintln(w)
		for _, f := range r.Fonts {
			if !r.FontsChecked {
				printRow(w, "?", f.Family, 11, "needs typst before it can be checked")
				continue
			}
			detail := ""
			if !f.Found {
				detail = f.URL
			}
			printRow(w, mark(f.Found), f.Family, 11, detail)
		}
		if r.FontNote != "" {
			fmt.Fprintf(w, "  %s\n", r.FontNote)
		}
	}

	fmt.Fprintln(w)
	if r.OK {
		fmt.Fprintln(w, "Ready — PDFs will render with the theme's intended fonts.")
	} else {
		fmt.Fprintln(w, "Not ready — install the items marked ✗ above, then re-run.")
	}
}

// listThemes prints the available theme names, one per line (the GUI reads this
// to fill the theme picker).
func listThemes() int {
	themes, err := pdfgen.ListThemes()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error listing themes: %v\n", err)
		return 1
	}
	for _, t := range themes {
		fmt.Println(t.Name)
	}
	return 0
}

// cmdPDFStatus prints an item's PDF-readiness: "none" (not fetched), "incomplete"
// (fetched but the cascade isn't done), or "complete" — mirroring browser-status
// so the GUI can warn before generating without reimplementing completeness.
func cmdPDFStatus(args []string) int {
	p := parseArgs(args, map[string]bool{
		"-c": true, "--course": true,
		"-p": true, "--path": true,
		"-l": true, "--lab": true,
	})
	table, kind, id := "", "", ""
	if v, ok := p.value("-c", "--course"); ok {
		table, kind, id = "courses", "course", firstID(v)
	} else if v, ok := p.value("-p", "--path"); ok {
		table, kind, id = "paths", "path", firstID(v)
	} else if v, ok := p.value("-l", "--lab"); ok {
		table, kind, id = "labs", "lab", firstID(v)
	}
	if id == "" {
		fmt.Println("none")
		return 0
	}
	switch {
	case !itemStored(p.portal, table, id):
		fmt.Println("none")
	case itemComplete(p.portal, kind, id):
		fmt.Println("complete")
	default:
		fmt.Println("incomplete")
	}
	return 0
}

func firstID(list string) string {
	ids := splitIDs(list)
	if len(ids) == 0 {
		return ""
	}
	return ids[0]
}

func capitalize(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}
