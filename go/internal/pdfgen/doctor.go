package pdfgen

// Doctor: report what the PDF pipeline still needs, and how to get it.
//
// Rendering shells out to pandoc + typst and draws the theme's fonts from the
// system font book (see renderTypstPandoc). None of that is bundled, and a
// missing font is worse than a missing tool: typst only WARNS ("unknown font
// family: lora") and still exits 0, so an unprepared machine silently produces a
// correct-but-wrong-looking PDF. This package therefore reports the whole
// pipeline up front — tools and fonts — plus the per-OS command to fix each gap,
// so the CLI and the GUI can guide instead of failing with a bare error.
//
// The guidance lives HERE rather than in the GUI so there is one copy for both
// front-ends; runtime.GOOS is the only OS branching in the core, and it is
// user-facing advice, never behaviour.

import (
	"os/exec"
	"runtime"
	"strings"
)

// Tool is an external program the pipeline shells out to.
type Tool struct {
	Name    string `json:"name"`
	Found   bool   `json:"found"`
	Path    string `json:"path,omitempty"`
	Version string `json:"version,omitempty"`
	Install string `json:"install,omitempty"` // command to install it on this OS
	URL     string `json:"url,omitempty"`     // where to get it manually
}

// Font is one family the active theme asks for.
type Font struct {
	Family string `json:"family"`
	Found  bool   `json:"found"`
	URL    string `json:"url,omitempty"` // where to download it
}

// Report is the full readiness picture for one theme.
type Report struct {
	OK bool `json:"ok"`
	// OS is the runtime platform the guidance was written for.
	OS    string `json:"os"`
	Theme string `json:"theme"`
	Tools []Tool `json:"tools"`
	Fonts []Font `json:"fonts"`
	// FontsChecked is false when typst is missing — we cannot enumerate the
	// system font book without it, so the font rows are "unknown", not "missing".
	FontsChecked bool `json:"fontsChecked"`
	// FontDir is where the user should drop font files on this OS.
	FontDir string `json:"fontDir"`
	// FontNote is the extra step (if any) needed after copying font files.
	FontNote string `json:"fontNote,omitempty"`
}

// Indirection points so the pure logic below can be unit-tested without pandoc,
// typst, or a particular system font book being installed.
var (
	lookPath        = exec.LookPath
	systemFontsFunc = systemFonts
)

// requiredTools is the pipeline, in the order it runs.
var requiredTools = []string{"pandoc", "typst"}

// fontSource maps the families the shipped themes use to their download page.
// All are SIL Open Font License, so a user may freely install them. Families we
// do not recognise still get reported; they simply carry no URL.
//
// Note: Google Sans is deliberately absent — it is Google's proprietary brand
// font, not published on Google Fonts and not licensed for redistribution, so it
// cannot be recommended, bundled, or fetched. Roboto / Open Sans / Noto Sans are
// the open families with a comparable feel.
var fontSource = map[string]string{
	"inter":     "https://fonts.google.com/specimen/Inter",
	"lora":      "https://fonts.google.com/specimen/Lora",
	"fira code": "https://fonts.google.com/specimen/Fira+Code",
	"noto sans": "https://fonts.google.com/specimen/Noto+Sans",
	"roboto":    "https://fonts.google.com/specimen/Roboto",
	"open sans": "https://fonts.google.com/specimen/Open+Sans",
}

// InstallHint returns the one-line command that installs tool on goos, or "" when
// there is no single obvious command (the caller then shows URL instead).
func InstallHint(tool, goos string) string {
	switch goos {
	case "darwin":
		return "brew install " + tool
	case "windows":
		switch tool {
		case "pandoc":
			return "winget install --id JohnMacFarlane.Pandoc"
		case "typst":
			return "winget install --id Typst.Typst"
		}
	case "linux":
		switch tool {
		case "pandoc":
			return "sudo apt install pandoc"
		case "typst":
			// Not packaged in most distro repos; the Rust toolchain install is
			// the one command that works everywhere.
			return "cargo install --locked typst-cli"
		}
	}
	return ""
}

// ToolURL is the project page for a tool, shown when there is no install command.
func ToolURL(tool string) string {
	switch tool {
	case "pandoc":
		return "https://pandoc.org/installing.html"
	case "typst":
		return "https://github.com/typst/typst/releases"
	}
	return ""
}

// FontInstallDir is the per-user font folder on goos — where a downloaded font
// file has to land for typst to see it.
func FontInstallDir(goos string) string {
	switch goos {
	case "darwin":
		return "~/Library/Fonts"
	case "windows":
		return `%LOCALAPPDATA%\Microsoft\Windows\Fonts`
	case "linux":
		return "~/.local/share/fonts"
	}
	return ""
}

// FontInstallNote is the extra step after copying files, or "" when there is none.
func FontInstallNote(goos string) string {
	switch goos {
	case "windows":
		return "Select the unzipped .ttf files, right-click, and choose Install."
	case "linux":
		return "Run `fc-cache -f` afterwards so the new fonts are picked up."
	}
	return ""
}

// parseFontFamilies turns `typst fonts` output into a family list. The command
// prints one family per line; blank lines are ignored.
func parseFontFamilies(out string) []string {
	var families []string
	for _, line := range strings.Split(out, "\n") {
		if f := strings.TrimSpace(line); f != "" {
			families = append(families, f)
		}
	}
	return families
}

// hasFamily reports whether family is present in available, case-insensitively
// (typst matches font families case-insensitively too).
func hasFamily(available []string, family string) bool {
	want := strings.ToLower(strings.TrimSpace(family))
	for _, a := range available {
		if strings.ToLower(strings.TrimSpace(a)) == want {
			return true
		}
	}
	return false
}

// systemFonts asks typst for the families it can see.
func systemFonts() ([]string, error) {
	out, err := exec.Command("typst", "fonts").Output()
	if err != nil {
		return nil, err
	}
	return parseFontFamilies(string(out)), nil
}

// toolVersion returns the first line of `<tool> --version`, or "" if it fails.
// Best-effort: a tool that is present but won't report a version is still usable.
func toolVersion(tool string) string {
	out, err := exec.Command(tool, "--version").Output()
	if err != nil {
		return ""
	}
	line, _, _ := strings.Cut(string(out), "\n")
	return strings.TrimSpace(line)
}

// Doctor reports what the PDF pipeline needs for the given theme on this machine.
// It never fails: everything it cannot determine is reported as not-found, which
// is exactly what the user needs to see.
func Doctor(t Theme) Report {
	r := Report{
		OS:       runtime.GOOS,
		Theme:    t.Name,
		FontDir:  FontInstallDir(runtime.GOOS),
		FontNote: FontInstallNote(runtime.GOOS),
	}

	typstFound := false
	for _, name := range requiredTools {
		tool := Tool{
			Name:    name,
			Install: InstallHint(name, runtime.GOOS),
			URL:     ToolURL(name),
		}
		if path, err := lookPath(name); err == nil {
			tool.Found = true
			tool.Path = path
			tool.Version = toolVersion(name)
			if name == "typst" {
				typstFound = true
			}
		}
		r.Tools = append(r.Tools, tool)
	}

	// Fonts can only be enumerated through typst; without it they stay unknown
	// rather than being reported as missing (which would be a guess).
	var available []string
	if typstFound {
		if fonts, err := systemFontsFunc(); err == nil {
			available = fonts
			r.FontsChecked = true
		}
	}
	for _, family := range t.Fonts {
		r.Fonts = append(r.Fonts, Font{
			Family: family,
			Found:  r.FontsChecked && hasFamily(available, family),
			URL:    fontSource[strings.ToLower(strings.TrimSpace(family))],
		})
	}

	r.OK = reportOK(r)
	return r
}

// reportOK is true when every tool is present and no declared font is known to be
// missing. Unchecked fonts do not block: typst is already reported missing, and
// that is the actionable gap.
func reportOK(r Report) bool {
	for _, t := range r.Tools {
		if !t.Found {
			return false
		}
	}
	if !r.FontsChecked {
		return false
	}
	for _, f := range r.Fonts {
		if !f.Found {
			return false
		}
	}
	return true
}
