"""The portfolio look: Inter served from the repo, the colours of Data-Generator in one place."""
import re

from purchase_planner import data, theme
from ui import theme as ui_theme

ASSETS = data.ROOT / "ui" / "assets"


def test_inter_comes_from_files_in_the_repo_and_no_font_service():
    css = (ASSETS / "fonts.css").read_text(encoding="utf-8")
    urls = re.findall(r"url\('([^']+)'\)", css)
    assert len(urls) == 2 and all((ASSETS / url).is_file() for url in urls)
    assert (ASSETS / "fonts" / "OFL-inter.txt").is_file()
    for path in [*ASSETS.rglob("*.css"), *(data.ROOT / "ui").glob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "googleapis" not in text and "gstatic" not in text, path


def test_style_sheet_tokens_match_the_shared_colours():
    css = (ASSETS / "style.css").read_text(encoding="utf-8")
    tokens = dict(re.findall(r"--dg-([a-z-]+):\s*([^;]+);", css))
    assert tokens["teal"] == theme.PRIMARY == "#006e79"
    assert tokens["copper"] == theme.ACCENT == "#c7692c"
    assert tokens["ink"] == theme.INK and tokens["text"] == theme.TEXT and tokens["muted"] == theme.MUTED
    assert tokens["line"] == theme.LINE and tokens["wash"] == theme.WASH
    assert tokens["sans"].startswith("'Inter'")
    assert "'tnum' 1" in tokens["num-features"]


def test_mantine_theme_uses_inter_and_the_teal_scale():
    mantine = ui_theme.MANTINE_THEME
    assert mantine["fontFamily"].startswith("'Inter'")
    assert mantine["colors"]["petrol"][mantine["primaryShade"]] == theme.PRIMARY
