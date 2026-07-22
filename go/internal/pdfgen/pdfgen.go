// Package pdfgen renders a stored item's Markdown to a styled PDF (backlog #5).
//
// The engine is pluggable via the theme manifest; the shipped engine is
// "typst-pandoc": Pandoc converts the Markdown to Typst and Typst renders it,
// using the theme's Typst template (theme/<name>/template.typ). Both tools must
// be on PATH. Themes live in theme/<name>/ with a theme.yaml manifest, so the
// look is data, not code, and new themes need no recompile.
package pdfgen

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"csb/internal/config"
	"gopkg.in/yaml.v3"
)

// DefaultTheme is used when no --theme is given.
const DefaultTheme = "humanist"

// ThemesDirName is the default themes folder, relative to the working dir.
const ThemesDirName = "theme"

// ThemesRoot resolves the themes directory: CSB_THEME_DIR > config paths.themes
// > "theme" (mirrors store.VaultRoot / DataRoot precedence).
func ThemesRoot() string {
	return config.Resolve("CSB_THEME_DIR", config.Get().Paths.Themes, ThemesDirName)
}

// Theme is a loaded theme manifest (theme/<name>/theme.yaml).
type Theme struct {
	Name        string `yaml:"name"`
	Description string `yaml:"description"`
	Engine      string `yaml:"engine"`
	Template    string `yaml:"template"`
	// Fonts are the families the template asks for, declared here so the
	// readiness check (see doctor.go) is data like the rest of the look, and a
	// new theme needs no recompile to be checkable. Typst only warns about a
	// missing family and still exits 0, so this list is what turns that silent
	// fallback into something we can report.
	Fonts []string `yaml:"fonts"`
	dir   string   // absolute theme directory
}

// TemplatePath is the absolute path to the theme's template file.
func (t Theme) TemplatePath() string { return filepath.Join(t.dir, t.Template) }

// ListThemes returns the discovered themes — subfolders of ThemesRoot that carry
// a valid theme.yaml — sorted by name. Folders without a manifest (e.g. sample
// dirs) are silently skipped, so they never appear as broken themes.
func ListThemes() ([]Theme, error) {
	root := ThemesRoot()
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	var out []Theme
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		if t, err := loadThemeDir(filepath.Join(root, e.Name())); err == nil {
			out = append(out, t)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

// LoadTheme loads a theme by name (DefaultTheme when name is empty).
func LoadTheme(name string) (Theme, error) {
	if name == "" {
		name = DefaultTheme
	}
	return loadThemeDir(filepath.Join(ThemesRoot(), name))
}

func loadThemeDir(dir string) (Theme, error) {
	b, err := os.ReadFile(filepath.Join(dir, "theme.yaml"))
	if err != nil {
		return Theme{}, err
	}
	var t Theme
	if err := yaml.Unmarshal(b, &t); err != nil {
		return Theme{}, err
	}
	if t.Name == "" {
		t.Name = filepath.Base(dir)
	}
	if t.Template == "" {
		t.Template = "template.typ"
	}
	if t.Engine == "" {
		t.Engine = "typst-pandoc"
	}
	if abs, err := filepath.Abs(dir); err == nil {
		dir = abs
	}
	t.dir = dir
	// A theme is only usable if its template exists.
	if _, err := os.Stat(t.TemplatePath()); err != nil {
		return Theme{}, fmt.Errorf("theme %q: template not found: %w", t.Name, err)
	}
	return t, nil
}

// PdfPathForMD returns the sibling .pdf path for a .md file.
func PdfPathForMD(mdPath string) string {
	return strings.TrimSuffix(mdPath, filepath.Ext(mdPath)) + ".pdf"
}

// Render converts an .md file to a .pdf using the theme's engine.
func Render(mdPath, pdfPath string, t Theme) error {
	switch t.Engine {
	case "", "typst-pandoc", "typst":
		return renderTypstPandoc(mdPath, pdfPath, t)
	default:
		return fmt.Errorf("unsupported theme engine %q (theme %q)", t.Engine, t.Name)
	}
}

// renderTypstPandoc shells out to `pandoc --pdf-engine=typst`, applying the
// theme's Typst template. --resource-path is the Markdown's own directory, so
// relative material images / links resolve. pandoc + typst must be on PATH.
func renderTypstPandoc(mdPath, pdfPath string, t Theme) error {
	if _, err := exec.LookPath("pandoc"); err != nil {
		return fmt.Errorf("pandoc not found on PATH (needed for PDF generation)")
	}
	if _, err := exec.LookPath("typst"); err != nil {
		return fmt.Errorf("typst not found on PATH (needed for PDF generation)")
	}
	if err := os.MkdirAll(filepath.Dir(pdfPath), 0o755); err != nil {
		return err
	}
	cmd := exec.Command("pandoc", mdPath,
		"--pdf-engine=typst",
		"--template="+t.TemplatePath(),
		"--resource-path="+filepath.Dir(mdPath),
		"-o", pdfPath,
	)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("pandoc/typst failed: %v\n%s", err, strings.TrimSpace(string(out)))
	}
	return nil
}
