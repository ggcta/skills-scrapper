package pdfgen

import (
	"errors"
	"testing"
)

func TestParseFontFamilies(t *testing.T) {
	// `typst fonts` prints one family per line; blank lines must not become
	// phantom families.
	got := parseFontFamilies("Inter\nLora\n\n  Fira Code  \n")
	want := []string{"Inter", "Lora", "Fira Code"}
	if len(got) != len(want) {
		t.Fatalf("got %d families %v, want %d", len(got), got, len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("family %d = %q, want %q", i, got[i], want[i])
		}
	}
}

func TestHasFamilyIsCaseInsensitive(t *testing.T) {
	// Typst matches families case-insensitively ("lora" resolves "Lora"), so the
	// check must not report a present font as missing over casing.
	available := []string{"Inter", "Fira Code"}
	if !hasFamily(available, "inter") {
		t.Error("inter should match Inter")
	}
	if !hasFamily(available, "  FIRA CODE  ") {
		t.Error("padded/uppercase FIRA CODE should match Fira Code")
	}
	if hasFamily(available, "Lora") {
		t.Error("Lora is not installed and must not match")
	}
}

func TestInstallHintPerOS(t *testing.T) {
	cases := []struct{ tool, goos, want string }{
		{"pandoc", "darwin", "brew install pandoc"},
		{"typst", "darwin", "brew install typst"},
		{"pandoc", "windows", "winget install --id JohnMacFarlane.Pandoc"},
		{"typst", "windows", "winget install --id Typst.Typst"},
		{"pandoc", "linux", "sudo apt install pandoc"},
		{"typst", "linux", "cargo install --locked typst-cli"},
		{"pandoc", "plan9", ""}, // unknown OS falls back to the URL
	}
	for _, c := range cases {
		if got := InstallHint(c.tool, c.goos); got != c.want {
			t.Errorf("InstallHint(%q, %q) = %q, want %q", c.tool, c.goos, got, c.want)
		}
	}
}

func TestFontInstallDirPerOS(t *testing.T) {
	cases := []struct{ goos, want string }{
		{"darwin", "~/Library/Fonts"},
		{"windows", `%LOCALAPPDATA%\Microsoft\Windows\Fonts`},
		{"linux", "~/.local/share/fonts"},
		{"plan9", ""},
	}
	for _, c := range cases {
		if got := FontInstallDir(c.goos); got != c.want {
			t.Errorf("FontInstallDir(%q) = %q, want %q", c.goos, got, c.want)
		}
	}
}

// stubTools points the doctor at a fake environment for the duration of a test.
func stubTools(t *testing.T, present map[string]bool, fonts []string, fontsErr error) {
	t.Helper()
	origLook, origFonts := lookPath, systemFontsFunc
	lookPath = func(name string) (string, error) {
		if present[name] {
			return "/usr/local/bin/" + name, nil
		}
		return "", errors.New("not found")
	}
	systemFontsFunc = func() ([]string, error) { return fonts, fontsErr }
	t.Cleanup(func() { lookPath, systemFontsFunc = origLook, origFonts })
}

func TestDoctorReportsMissingTool(t *testing.T) {
	stubTools(t, map[string]bool{"typst": true}, []string{"Inter"}, nil)
	r := Doctor(Theme{Name: "humanist", Fonts: []string{"Inter"}})
	if r.OK {
		t.Error("report must not be OK when pandoc is missing")
	}
	var pandoc Tool
	for _, tool := range r.Tools {
		if tool.Name == "pandoc" {
			pandoc = tool
		}
	}
	if pandoc.Found {
		t.Error("pandoc should be reported missing")
	}
	if pandoc.Install == "" && pandoc.URL == "" {
		t.Error("a missing tool must carry actionable guidance")
	}
}

func TestDoctorReportsMissingFont(t *testing.T) {
	// The silent-failure case: both tools present, so rendering "works", but the
	// theme's body font is absent and the PDF would quietly use a fallback.
	stubTools(t, map[string]bool{"pandoc": true, "typst": true}, []string{"Inter"}, nil)
	r := Doctor(Theme{Name: "humanist", Fonts: []string{"Inter", "Lora"}})
	if r.OK {
		t.Error("report must not be OK when a declared font is missing")
	}
	if !r.FontsChecked {
		t.Error("fonts should be checked when typst is present")
	}
	byFamily := map[string]Font{}
	for _, f := range r.Fonts {
		byFamily[f.Family] = f
	}
	if !byFamily["Inter"].Found {
		t.Error("Inter is installed and should be found")
	}
	if byFamily["Lora"].Found {
		t.Error("Lora is not installed and should be reported missing")
	}
	if byFamily["Lora"].URL == "" {
		t.Error("a missing known font must carry a download URL")
	}
}

func TestDoctorLeavesFontsUncheckedWithoutTypst(t *testing.T) {
	// Without typst we cannot enumerate the font book. Reporting the fonts as
	// "missing" would be a guess; they must stay unchecked instead.
	stubTools(t, map[string]bool{"pandoc": true}, nil, errors.New("no typst"))
	r := Doctor(Theme{Name: "humanist", Fonts: []string{"Inter"}})
	if r.FontsChecked {
		t.Error("fonts must not be reported as checked without typst")
	}
	if r.Fonts[0].Found {
		t.Error("an unchecked font must not be reported as found")
	}
	if r.OK {
		t.Error("report must not be OK when typst is missing")
	}
}

func TestDoctorOKWhenEverythingPresent(t *testing.T) {
	stubTools(t, map[string]bool{"pandoc": true, "typst": true},
		[]string{"Inter", "Lora", "Fira Code", "Noto Sans"}, nil)
	r := Doctor(Theme{Name: "humanist", Fonts: []string{"Inter", "Lora", "Fira Code", "Noto Sans"}})
	if !r.OK {
		t.Errorf("report should be OK with every tool and font present: %+v", r)
	}
}
