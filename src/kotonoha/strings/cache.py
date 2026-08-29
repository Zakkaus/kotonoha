"""Localized labels for the local lyrics-cache management window."""

from typing import Final

CACHE_STRINGS: Final[dict[str, dict[str, str]]] = {
    "btn.manage_cache": {
        "en": "Local lyrics cache",
        "zh-Hans": "本地歌词缓存",
        "zh-Hant": "本地歌詞快取",
        "ja": "ローカル歌詞キャッシュ",
    },
    "cache.title": {
        "en": "Local lyrics cache",
        "zh-Hans": "本地歌词缓存",
        "zh-Hant": "本地歌詞快取",
        "ja": "ローカル歌詞キャッシュ",
    },
    "cache.subtitle": {
        "en": "Search cached lyric metadata and remove incorrect entries.",
        "zh-Hans": "搜索缓存歌词信息，并删除有误的条目。",
        "zh-Hant": "搜尋快取歌詞資訊，並刪除有誤的項目。",
        "ja": "キャッシュされた歌詞情報を検索し、誤った項目を削除します。",
    },
    "cache.search_placeholder": {
        "en": "Search title, artist, album, provider or ID",
        "zh-Hans": "搜索标题、艺术家、专辑、来源或 ID",
        "zh-Hant": "搜尋標題、藝人、專輯、來源或 ID",
        "ja": "タイトル、アーティスト、アルバム、ソース、IDを検索",
    },
    "btn.search_cache": {
        "en": "Search",
        "zh-Hans": "搜索",
        "zh-Hant": "搜尋",
        "ja": "検索",
    },
    "btn.delete_cache": {
        "en": "Delete selected",
        "zh-Hans": "删除选中",
        "zh-Hant": "刪除選取項目",
        "ja": "選択項目を削除",
    },
    "cache.delete_tooltip": {
        "en": "Delete the selected cache entries",
        "zh-Hans": "删除选中的缓存条目",
        "zh-Hant": "刪除選取的快取項目",
        "ja": "選択したキャッシュ項目を削除",
    },
    "cache.loading": {
        "en": "Loading…",
        "zh-Hans": "加载中…",
        "zh-Hant": "載入中…",
        "ja": "読み込み中…",
    },
    "cache.results": {
        "en": "{count} entries",
        "zh-Hans": "{count} 个条目",
        "zh-Hant": "{count} 個項目",
        "ja": "{count} 件",
    },
    "cache.no_results": {
        "en": "No matching entries",
        "zh-Hans": "没有匹配的条目",
        "zh-Hant": "沒有符合的項目",
        "ja": "一致する項目はありません",
    },
    "cache.delete_confirm": {
        "en": "Delete {count} selected cache entries?",
        "zh-Hans": "确定删除选中的 {count} 个缓存条目吗？",
        "zh-Hant": "確定刪除選取的 {count} 個快取項目嗎？",
        "ja": "選択した {count} 件のキャッシュを削除しますか？",
    },
    "cache.clear_confirm": {
        "en": "Delete every local lyrics cache entry?",
        "zh-Hans": "确定删除全部本地歌词缓存吗？",
        "zh-Hant": "確定刪除全部本地歌詞快取嗎？",
        "ja": "ローカル歌詞キャッシュをすべて削除しますか？",
    },
    "cache.deleted": {
        "en": "Deleted {count} entries",
        "zh-Hans": "已删除 {count} 个条目",
        "zh-Hant": "已刪除 {count} 個項目",
        "ja": "{count} 件を削除しました",
    },
    "cache.deleted_partial": {
        "en": "Deleted {deleted} entries; {missing} were already absent",
        "zh-Hans": "已删除 {deleted} 个条目，{missing} 个条目已不存在",
        "zh-Hant": "已刪除 {deleted} 個項目，{missing} 個項目已不存在",
        "ja": "{deleted} 件を削除しました（{missing} 件はすでにありません）",
    },
    "cache.clear_done": {
        "en": "Lyrics cache cleared",
        "zh-Hans": "歌词缓存已清除",
        "zh-Hant": "歌詞快取已清除",
        "ja": "歌詞キャッシュを消去しました",
    },
    "cache.column.provider": {
        "en": "Provider",
        "zh-Hans": "来源",
        "zh-Hant": "來源",
        "ja": "プロバイダー",
    },
    "cache.column.title": {
        "en": "Title",
        "zh-Hans": "标题",
        "zh-Hant": "標題",
        "ja": "タイトル",
    },
    "cache.column.artist": {
        "en": "Artist",
        "zh-Hans": "艺术家",
        "zh-Hant": "藝人",
        "ja": "アーティスト",
    },
    "cache.column.album": {
        "en": "Album",
        "zh-Hans": "专辑",
        "zh-Hant": "專輯",
        "ja": "アルバム",
    },
    "cache.column.fetched": {
        "en": "Fetched",
        "zh-Hans": "获取时间",
        "zh-Hant": "取得時間",
        "ja": "取得日時",
    },
    "cache.column.accessed": {
        "en": "Last used",
        "zh-Hans": "最近使用",
        "zh-Hant": "最近使用",
        "ja": "最終使用",
    },
    "cache.column.mode": {
        "en": "Mode",
        "zh-Hans": "模式",
        "zh-Hant": "模式",
        "ja": "モード",
    },
    "cache.mode.auto": {
        "en": "AUTO",
        "zh-Hans": "AUTO",
        "zh-Hant": "AUTO",
        "ja": "AUTO",
    },
    "cache.mode.manual": {
        "en": "Manual",
        "zh-Hans": "手动",
        "zh-Hant": "手動",
        "ja": "手動",
    },
}

__all__ = ["CACHE_STRINGS"]
