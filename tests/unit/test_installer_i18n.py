"""[lint-guard:ps1-i18n] install.ps1 的四語 key 集合一致性——非 Python 檔案的內部
一致性檢查；現有 eslint/stylelint/scripts/*.mjs 都不吃 .ps1，CD-145b-5 已定案用
pytest 頂替 lint 的角色。
"""
import re
from pathlib import Path

INSTALL_PS1 = Path(__file__).resolve().parent.parent.parent / "install.ps1"
_LANGS = ("zh-TW", "zh-CN", "ja", "en")

_LANG_BLOCK_RE = re.compile(
    r"^    '(zh-TW|zh-CN|ja|en)' = @\{\r?\n(.*?)\r?\n    \}\r?\n",
    re.MULTILINE | re.DOTALL,
)
_KEY_RE = re.compile(r"^        ([A-Za-z0-9_]+)\s*=", re.MULTILINE)


def _extract_lang_keysets(ps1_text: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for lang, body in _LANG_BLOCK_RE.findall(ps1_text):
        result[lang] = set(_KEY_RE.findall(body))
    return result


def test_install_ps1_language_keysets_equal():  # [lint-guard:ps1-i18n]
    text = INSTALL_PS1.read_text(encoding="utf-8")
    keysets = _extract_lang_keysets(text)
    assert set(keysets.keys()) == set(_LANGS), (
        f"install.ps1 語言區塊掃描不到全部四語，只抓到 {sorted(keysets.keys())}"
        "——先確認縮排是不是 CD-145b-10 定死的 4/8 空格格式"
    )
    reference_lang, reference_keys = "zh-TW", keysets["zh-TW"]
    assert len(reference_keys) >= 20, "zh-TW key 數量低於預期下限，抽取邏輯可能沒抓到東西（空翻假綠）"
    for lang in _LANGS:
        diff = keysets[lang].symmetric_difference(reference_keys)
        assert not diff, f"{lang} 與 {reference_lang} 的 key 集合不相等，差異：{sorted(diff)}"


INSTALL_SH = Path(__file__).resolve().parent.parent.parent / "install.sh"

_SH_TABLE_RE = re.compile(
    r'^    case "\$\{LANG_KEY\}:\$1" in\n(.*?)\n    esac\n',
    re.MULTILINE | re.DOTALL,
)
_SH_KEY_LINE_RE = re.compile(r'^        (zh-TW|zh-CN|ja|en):([A-Za-z0-9_]+)\) echo "([^"]*)" ;;$', re.MULTILINE)


def _extract_sh_lang_keysets(sh_text: str):
    m = _SH_TABLE_RE.search(sh_text)
    assert m is not None, (
        "install.sh 找不到 `case \"${LANG_KEY}:$1\" in ... esac` 語言表區塊——"
        "CD-145b-17 的縮排格式可能被改動，fail-closed 直接判失敗，不對整檔掃描"
    )
    result: dict[str, set[str]] = {}
    for lang, key, _val in _SH_KEY_LINE_RE.findall(m.group(1)):
        result.setdefault(lang, set()).add(key)
    return result, m


def test_install_sh_language_keysets_equal():  # [lint-guard:ps1-i18n]
    text = INSTALL_SH.read_text(encoding="utf-8")
    keysets, _m = _extract_sh_lang_keysets(text)
    assert set(keysets.keys()) == set(_LANGS), (
        f"install.sh 語言表只抓到 {sorted(keysets.keys())}，缺少的語言 case 分支"
        "可能沒寫全，或縮排不符 CD-145b-17 格式"
    )
    reference_keys = keysets["zh-TW"]
    assert len(reference_keys) >= 15, "zh-TW key 數量低於預期下限，抽取邏輯可能沒抓到東西（空翻假綠）"
    for lang in _LANGS:
        diff = keysets[lang].symmetric_difference(reference_keys)
        assert not diff, f"install.sh：{lang} 與 zh-TW 的 key 集合不相等，差異：{sorted(diff)}"


