"""
test_agent3_seo.py — Tests unitarios para las funciones puras de SEO en
agentes/agent3_viral_scorer.py (_format_seo_context, _merge_hashtags).
"""

from agentes.agent3_viral_scorer import _format_seo_context, _merge_hashtags


# ─────────────────────────────────────────
#  _merge_hashtags
# ─────────────────────────────────────────

def test_merge_hashtags_dedup_preserva_orden():
    assert _merge_hashtags(["#a", "#b"], ["#b", "#c"]) == ["#a", "#b", "#c"]


def test_merge_hashtags_base_vacio():
    assert _merge_hashtags([], ["#a", "#b"]) == ["#a", "#b"]


def test_merge_hashtags_extra_vacio():
    assert _merge_hashtags(["#a", "#b"], []) == ["#a", "#b"]


def test_merge_hashtags_ambos_vacios():
    assert _merge_hashtags([], []) == []


def test_merge_hashtags_tolera_none():
    assert _merge_hashtags(None, None) == []
    assert _merge_hashtags(["#a"], None) == ["#a"]


# ─────────────────────────────────────────
#  _format_seo_context
# ─────────────────────────────────────────

def test_format_seo_context_vacio_retorna_string_vacio():
    assert _format_seo_context({}) == ""
    assert _format_seo_context(None) == ""


def test_format_seo_context_incluye_fecha_y_plataformas():
    seo_base = {
        "actualizado": "2026-07-31",
        "tiktok": {"hashtags": ["#kickperu", "#fyp"], "notas": "nota tiktok"},
        "youtube_shorts": {
            "hashtags": ["#Shorts", "#Peru"],
            "tags_backend": ["streamers peru"],
            "notas": "nota youtube",
        },
    }
    texto = _format_seo_context(seo_base)
    assert "2026-07-31" in texto
    assert "TikTok:" in texto
    assert "#kickperu, #fyp" in texto
    assert "nota tiktok" in texto
    assert "YouTube Shorts:" in texto
    assert "#Shorts, #Peru" in texto
    assert "streamers peru" in texto
    assert "nota youtube" in texto


def test_format_seo_context_omite_plataforma_sin_datos():
    seo_base = {
        "actualizado": "2026-07-31",
        "tiktok": {"hashtags": ["#kickperu"], "notas": ""},
        "youtube_shorts": {"hashtags": [], "tags_backend": [], "notas": ""},
    }
    texto = _format_seo_context(seo_base)
    assert "TikTok:" in texto
    assert "YouTube Shorts:" not in texto


def test_format_seo_context_facebook_reels_vacio_no_aparece():
    seo_base = {
        "actualizado": "2026-07-31",
        "tiktok": {"hashtags": ["#kickperu"], "notas": ""},
        "facebook_reels": {"hashtags": [], "notas": ""},
    }
    texto = _format_seo_context(seo_base)
    assert "Facebook" not in texto
