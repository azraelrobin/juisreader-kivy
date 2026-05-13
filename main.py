#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JuisReader Kivy - 手机版 TXT 阅读器
需要：pip install kivy requests Pillow
Windows 环境需要先安装 SDL2：https://github.com/libsdl-org/SDL/releases
或者：pip install kivy[full]
"""
import os, sys, re, json, hashlib, pickle, threading, base64
from urllib.parse import unquote, urljoin

# Windows 上确保 UTF-8
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except:
        pass

try:
    from kivy.app import App
    from kivy.lang import Builder
    from kivy.uix.screenmanager import ScreenManager, Screen
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.label import Label
    from kivy.uix.button import Button
    from kivy.uix.textinput import TextInput
    from kivy.uix.popup import Popup
    from kivy.uix.progressbar import ProgressBar
    from kivy.storage.jsonstore import JsonStore
    from kivy.properties import StringProperty, NumericProperty, BooleanProperty, ListProperty
    from kivy.clock import Clock
    from kivy.core.window import Window
    from kivy.core.text import LabelBase
except ImportError as e:
    print(f"Kivy 导入失败: {e}")
    print("请先安装：pip install kivy requests Pillow")
    if sys.platform == "win32":
        input("按回车退出...")
    sys.exit(1)

# 注册中文字体
def _register_chinese_font():
    import shutil
    from kivy.utils import platform
    
    # 打包的 TTF（与 main.py 同目录）
    src_font = os.path.join(os.path.dirname(__file__), "NotoSansSC.ttf")
    
    # Kivy 字体目录
    if platform == "android":
        kivy_font_dir = "/sdcard/.kivy/fonts"
    else:
        kivy_font_dir = os.path.join(os.path.expanduser("~"), ".kivy", "fonts")
    os.makedirs(kivy_font_dir, exist_ok=True)
    dest_font = os.path.join(kivy_font_dir, "NotoSansSC.ttf")
    
    # 复制字体到 Kivy 字体目录
    if os.path.exists(src_font) and not os.path.exists(dest_font):
        try:
            shutil.copy2(src_font, dest_font)
            print(f"[FONT] Copied font to {dest_font}")
        except Exception as e:
            print(f"[FONT] Copy failed: {e}")
    
    # 注册字体（用完整路径，不复制）
    for fp in [src_font, dest_font]:
        if os.path.exists(fp):
            try:
                LabelBase.register(name="NotoSansSC", fn_regular=fp)
                print(f"[FONT] Registered NotoSansSC from {fp}")
                return "NotoSansSC"
            except Exception as e:
                print(f"[FONT] Failed {fp}: {e}")
    
    # 字体文件都不存在：用系统回退字体（不注册，直接让 KV 用系统默认）
    print(f"[FONT] WARNING: No font file found (src={src_font}, dest={dest_font})")
    return "Roboto"

CHINESE_FONT = _register_chinese_font()

import requests
from requests.auth import HTTPBasicAuth

# ========== 配置 ==========
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".juisreader_kivy.json")
STORE = JsonStore(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else JsonStore(CONFIG_FILE)

FONT_DEFAULTS = {
    "name": CHINESE_FONT,
    "size": 18,
    "bg": "#f5f5f0",
    "fg": "#1a1a1a",
    "night_bg": "#2a2a2a",
    "night_fg": "#cccccc",
    "line_height": 8,
}

# ========== 缓存 ==========
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".juisreader_kivy_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def load_cache_index():
    idx_file = os.path.join(CACHE_DIR, "index.pkl")
    if os.path.exists(idx_file):
        try:
            return pickle.load(open(idx_file, "rb"))
        except:
            pass
    return {}


def save_cache_index(idx):
    idx_file = os.path.join(CACHE_DIR, "index.pkl")
    pickle.dump(idx, open(idx_file, "wb"))


def get_config(key, default=None):
    try:
        return STORE.get(key)
    except:
        return default


# ========== WebDAV ==========
def webdav_list_dir(folder_url, user, pwd):
    """列出 WebDAV 目录下的所有 .txt 文件"""
    import xml.etree.ElementTree as ET

    folder_url = folder_url.rstrip("/")
    headers = {"Content-Type": "application/xml"}
    if user and pwd:
        headers["Authorization"] = "Basic " + base64.b64encode(
            f"{user}:{pwd}".encode()).decode()

    body = b'<?xml version="1.0" encoding="utf-8"?><D:propfind xmlns:D="DAV:"><D:allprop/></D:propfind>'

    try:
        resp = requests.request("PROPFIND", folder_url, headers=headers, data=body, timeout=20)
        if resp.status_code not in (200, 207):
            return False, f"HTTP {resp.status_code}"

        ns = {"d": "DAV:"}
        root = ET.fromstring(resp.content)
        results = []
        for r in root.findall(".//d:response", ns):
            href = r.find("d:href", ns)
            if href is None:
                continue
            raw_path = unquote(unquote(href.text or ""))
            resource = r.find("d:resourcetype", ns)
            if resource is not None and resource.find("d:collection", ns) is not None:
                continue
            if raw_path.lower().endswith((".txt", ".md")):
                filename = raw_path.split("/")[-1]
                from urllib.parse import urlparse
                parsed = urlparse(folder_url)
                file_url = f"{parsed.scheme}://{parsed.netloc}{raw_path}"
                results.append((filename, file_url))

        results.sort(key=lambda x: x[0])
        return True, results
    except Exception as e:
        return False, str(e)


def webdav_fetch_file(file_url, user, pwd):
    """下载 WebDAV 文件"""
    headers = {}
    if user and pwd:
        headers["Authorization"] = "Basic " + base64.b64encode(
            f"{user}:{pwd}".encode()).decode()

    try:
        resp = requests.get(file_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        last_modified = resp.headers.get("Last-Modified", "")
        return True, resp.content, last_modified
    except Exception as e:
        return False, str(e)


# ========== WebDAV 进度同步 ==========
PROGRESS_FILE = os.path.join(os.path.expanduser("~"), ".juisreader_kivy_progress.json")
WEBDAV_PROGRESS_FILE = "juisreader_kivy_progress.json"

def _webdav_request(method, url, data=None, headers=None):
    """发送 WebDAV 请求"""
    cfg = get_config("webdav", {}) or {}
    if not cfg.get("folder"):
        return False, "未配置 WebDAV"
    
    url = url.rstrip("/")
    headers = dict(headers) if headers else {}
    user = cfg.get("user", "")
    pwd = cfg.get("pwd", "")
    if user:
        creds = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    headers["Content-Type"] = "application/xml"
    
    try:
        resp = requests.request(method, url, headers=headers, data=data, timeout=15)
        return True, resp.content if resp.status_code != 204 else None
    except Exception as e:
        return False, str(e)

def webdav_sync_push():
    """上传进度到 WebDAV"""
    cfg = get_config("webdav", {}) or {}
    if not cfg.get("folder"):
        return False, "未配置 WebDAV"
    
    # 收集本地进度
    progress_data = {}
    for key in STORE.keys():
        if key.startswith("progress_"):
            try:
                d = STORE.get(key)
                book_url = d.get("url", "")
                if book_url:
                    progress_data[book_url] = d
            except:
                pass
    
    data = json.dumps(progress_data, ensure_ascii=False).encode("utf-8")
    folder = cfg["folder"].rstrip("/")
    remote_url = f"{folder}/{WEBDAV_PROGRESS_FILE}"
    
    ok, res = _webdav_request("PUT", remote_url, data)
    if ok:
        return True, "上传成功"
    
    # 404 -> 创建目录再上传
    dir_url = remote_url.rsplit("/", 1)[0]
    _webdav_request("MKCOL", dir_url)
    ok2, _ = _webdav_request("PUT", remote_url, data)
    return ok2, "上传成功" if ok2 else str(res)

def webdav_sync_pull():
    """从 WebDAV 下载进度"""
    cfg = get_config("webdav", {}) or {}
    if not cfg.get("folder"):
        return False, "未配置 WebDAV"
    
    folder = cfg["folder"].rstrip("/")
    remote_url = f"{folder}/{WEBDAV_PROGRESS_FILE}"
    ok, data = _webdav_request("GET", remote_url)
    if not ok:
        return False, data
    
    try:
        remote_progress = json.loads(data.decode("utf-8", errors="replace"))
    except:
        return False, "服务器数据格式错误"
    
    # 合并：远程为准，保留本地书签
    for book_url, rdata in remote_progress.items():
        key = f"progress_{hashlib.md5(book_url.encode()).hexdigest()[:8]}"
        try:
            local = STORE.get(key) if STORE.exists(key) else {}
        except:
            local = {}
        # 书签合并去重
        remote_bm = rdata.get("bookmarks", [])
        local_bm = local.get("bookmarks", [])
        seen = {bm.get("text", "") for bm in remote_bm}
        for bm in local_bm:
            if bm.get("text", "") not in seen:
                rdata.setdefault("bookmarks", []).append(bm)
        STORE.put(key, **rdata)
    
    return True, "同步成功"

def webdav_sync_status():
    """检查同步状态"""
    cfg = get_config("webdav", {}) or {}
    if not cfg.get("folder"):
        return "未配置"
    return "已配置"


def detect_encoding(data):
    """检测最佳编码"""
    sample = data[:16384]
    candidates = [("utf-8","utf-8"), ("gbk","gbk"), ("gb2312","gb2312"),
                  ("gb18030","gb18030"), ("big5","big5")]
    best_enc, best_score = "utf-8", -1
    for name, enc in candidates:
        try:
            text = sample.decode(enc, errors="replace")
            score = sum(1 for c in text if "\u4e00" <= c <= "\u9fff") * 10 - text.count("\ufffd") * 100
            if score > best_score:
                best_score, best_enc = score, enc
        except:
            pass
    return best_enc


def extract_chapters(content):
    """提取章节"""
    chapters = []
    chinese_nums = "一二三四五六七八九十百千万零"
    pos = 0
    for line in content.split('\n'):
        ls = line.strip()
        if 4 <= len(ls) <= 60:
            m = re.match(rf'^第([{chinese_nums}\d]+)([章节篇部集卷])\s*[.、:：]?\s*(.*)$', ls)
            if m:
                num, unit, title = m.groups()
                chapters.append((f"第{num}{unit}{title}", pos))
            else:
                m2 = re.match(r'^Chapter\s*(\d+)[.:：]?\s*(.*)$', ls, re.IGNORECASE)
                if m2:
                    num, title = m2.groups()
                    chapters.append((f"Chapter {num} {title}", pos))
        pos += len(line) + 1
    return chapters


# ========== 主阅读界面 ==========
class ReaderScreen(Screen):
    content = StringProperty("")
    title = StringProperty("")
    chapters = ListProperty([])
    current_chapter = NumericProperty(0)
    total_chars = NumericProperty(0)
    night_mode = BooleanProperty(False)
    font_size = NumericProperty(18)
    line_height = NumericProperty(8)
    content_height = NumericProperty(1000)
    is_loading = BooleanProperty(False)
    webdav_user = StringProperty("")
    webdav_pwd = StringProperty("")
    current_file_url = StringProperty("")
    loaded_end = NumericProperty(0)
    CHUNK_SIZE = 50000
    page_size = 1200  # chars per page
    current_page = 0
    total_pages = 1

    def on_enter(self):
        self.load_settings()
        self.apply_theme()

    def load_settings(self):
        cfg = get_config("webdav", {}) or {}
        self.webdav_user = cfg.get("user", "")
        self.webdav_pwd = cfg.get("pwd", "")

    def apply_theme(self):
        if self.night_mode:
            self.ids.content_label.color = (0.8, 0.8, 0.8, 1)
        else:
            self.ids.content_label.color = (0.2, 0.2, 0.2, 1)
        self.ids.content_label.font_name = CHINESE_FONT
        self.ids.content_label.font_size = self.font_size
        self.ids.content_label.line_height = self.font_size + self.line_height

    def on_touch_down(self, touch):
        if self.collide_point(touch.x, touch.y):
            w, h = self.size
            if 0.3*w < touch.x < 0.7*w and 0.2*h < touch.y < 0.8*h:
                tb = self.ids.toolbar
                if tb.opacity == 0:
                    tb.opacity = 1
                    tb.height = "56dp"
                else:
                    tb.opacity = 0
                    tb.height = "0dp"
            return super().on_touch_down(touch)
        return super().on_touch_down(touch)

    def load_from_url(self, file_url, title, user="", pwd=""):
        self.is_loading = True
        self.title = title
        self.current_file_url = file_url
        if user:
            self.webdav_user = user
        if pwd:
            self.webdav_pwd = pwd

        def do_load():
            # 查缓存
            cache_index = load_cache_index()
            cached = cache_index.get(file_url)
            cache_dir = get_config("cache_dir", {"v": CACHE_DIR})["v"] or CACHE_DIR
            os.makedirs(cache_dir, exist_ok=True)
            cache_key = hashlib.md5(file_url.encode()).hexdigest()
            cache_file = os.path.join(cache_dir, f"{cache_key}.txt")

            raw_data = None
            last_modified = None

            if cached and os.path.exists(cache_file):
                try:
                    # HEAD 检查
                    h = {}
                    if self.webdav_user:
                        h["Authorization"] = "Basic " + base64.b64encode(
                            f"{self.webdav_user}:{self.webdav_pwd}".encode()).decode()
                    head_resp = requests.head(file_url, headers=h, timeout=10)
                    srv_lm = head_resp.headers.get("Last-Modified", "")
                    if srv_lm and srv_lm == cached[1]:
                        with open(cache_file, "rb") as f:
                            raw_data = f.read()
                    elif not srv_lm:
                        with open(cache_file, "rb") as f:
                            raw_data = f.read()
                except:
                    pass

            if not raw_data:
                ok, data_or_err, lm = None, None, ""
                if self.webdav_user:
                    resp = requests.get(file_url, auth=HTTPBasicAuth(self.webdav_user, self.webdav_pwd), timeout=30)
                else:
                    resp = requests.get(file_url, timeout=30)
                if resp.status_code == 200:
                    raw_data = resp.content
                    last_modified = resp.headers.get("Last-Modified", "")
                    # 写缓存
                    try:
                        with open(cache_file, "wb") as f:
                            f.write(raw_data)
                        cache_index[file_url] = (cache_file, last_modified)
                        save_cache_index(cache_index)
                    except:
                        pass

            if not raw_data:
                Clock.schedule_once(lambda dt: self._show_error("加载失败"), 0)
                return

            enc = detect_encoding(raw_data)
            content = raw_data.decode(enc, errors="replace")
            chapters = extract_chapters(content)

            Clock.schedule_once(lambda dt: self._show_content(content, chapters), 0)

        threading.Thread(target=do_load, daemon=True).start()

    def _refresh_content_height(self):
        """刷新内容区域高度"""
        try:
            ti = self.ids.content_label
            # TextInput: use _get_text_height() for content height
            try:
                content_h = ti._get_text_height(
                    ti._lines[:ti._lines_drawable],
                    ti.width - ti.padding[0] * 2,
                    ti._lbl
                )
            except Exception:
                content_h = len(ti.text) * self.font_size * 1.5
            new_h = content_h + ti.padding[1] * 2
            if new_h > self.content_height:
                self.content_height = new_h
            ti.height = self.content_height
            print(f"[DEBUG] _refresh_content_height: content_h={content_h}, ti.height={ti.height}")
        except Exception as e:
            print(f"[DEBUG] _refresh_content_height error: {e}")

    def _scroll_to_bottom(self):
        """翻页模式不需要滚动到底部"""
        pass

    def _show_content(self, content, chapters):
        self.content = content
        self.total_chars = len(content)
        self.chapters = chapters
        self.loaded_end = 0
        self.is_loading = False
        self.current_page = 0
        # Update pagination
        self._update_total_pages()
        # Show first page
        self.ids.content_label.text = ""
        print(f"[DEBUG] _show_content: content_len={len(content)}, chapters={len(chapters)}, pages={self.total_pages}")
        self._show_page()
        # Load all content in background
        self._append_chunk()

    def _append_chunk(self):
        """预加载全部内容"""
        if not self.content or len(self.content) == 0:
            print(f"[DEBUG] _append_chunk: content is empty!")
            return
        if self.loaded_end >= len(self.content):
            print(f"[DEBUG] _append_chunk: all loaded, updating pagination")
            self._update_total_pages()
            return
        end = min(self.loaded_end + self.CHUNK_SIZE, len(self.content))
        chunk = self.content[self.loaded_end:end]
        print(f"[DEBUG] _append_chunk: preloading {self.loaded_end}:{end}")
        self.loaded_end = end
        Clock.schedule_once(lambda dt: self._append_chunk(), 0.05)

    def _show_error(self, msg):
        self.is_loading = False
        popup = Popup(title="错误", content=Label(text=msg, valign="middle"),
                      size_hint=(0.8, 0.3))
        popup.open()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._show_page()

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._show_page()
        elif self.loaded_end < len(self.content):
            self._append_chunk()

    def _show_page(self):
        """显示当前页内容"""
        if not self.content:
            return
        start = self.current_page * self.page_size
        end = min(start + self.page_size, len(self.content))
        page_text = self.content[start:end]
        self.ids.content_label.text = page_text
        self.ids.content_label.height = max(1000, len(page_text) * 0.5)
        # Update page indicator
        self.ids.chapter_label.text = f"第 {self.current_page + 1} / {self.total_pages} 页"
        print(f"[DEBUG] _show_page: page {self.current_page + 1}/{self.total_pages}, chars {start}:{end}")

    def _update_total_pages(self):
        if self.page_size <= 0:
            self.total_pages = 1
        else:
            self.total_pages = max(1, (len(self.content) + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, self.total_pages - 1)

    def toggle_toolbar(self):
        """点击内容区显示/隐藏工具栏"""
        tb = self.ids.toolbar
        if tb.opacity > 0.5:
            tb.opacity = 0
            tb.height = "0dp"
        else:
            tb.opacity = 1
            tb.height = "50dp"

    def toggle_night(self):
        self.night_mode = not self.night_mode
        self.apply_theme()

    def change_font_size(self, delta):
        self.font_size = max(12, min(32, self.font_size + delta))
        self.ids.content_label.font_name = CHINESE_FONT
        self.ids.content_label.font_size = self.font_size
        self.ids.content_label.line_height = self.font_size + self.line_height

    def change_line_height(self, delta):
        self.line_height = max(2, min(30, self.line_height + delta))
        self.ids.content_label.line_height = self.font_size + self.line_height

    def show_chapters(self):
        if not self.chapters:
            return
        btn_container = BoxLayout(orientation="vertical", size_hint_y=None, padding=5, spacing=5)
        total = len(self.chapters)
        btn_container.height = total * 50
        for i, (title, pos) in enumerate(self.chapters):
            btn = Button(
                text=f"{i+1}. {title}",
                size_hint_y=None,
                height="45dp",
                background_color=(0.2, 0.45, 0.9, 1),
                color=(1, 1, 1, 1),
                on_press=lambda _, p=pos: self._goto_chapter(p)
            )
            btn_container.add_widget(btn)
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(btn_container)
        self._chapter_popup = Popup(title="目录", content=scroll, size_hint=(0.9, 0.7))
        self._chapter_popup.open()

    def _goto_chapter(self, pos):
        if hasattr(self, '_chapter_popup') and self._chapter_popup:
            self._chapter_popup.dismiss()
            self._chapter_popup = None
        if not self.content:
            return
        page = pos // self.page_size
        page = max(0, min(page, self.total_pages - 1))
        self.current_page = page
        self._show_page()

    def save_progress(self, *args):
        if not self.current_file_url:
            return
        pct = (self.current_page / max(1, self.total_pages - 1)) * 100 if self.total_pages > 1 else 0
        key = f"progress_{hashlib.md5(self.current_file_url.encode()).hexdigest()[:8]}"
        STORE.put(key, url=self.current_file_url, pct=pct)


# ========== 书架界面 ==========
class BookshelfScreen(Screen):
    webdav_folder = StringProperty("")
    webdav_user = StringProperty("")
    webdav_pwd = StringProperty("")
    cache_dir = StringProperty(CACHE_DIR)
    file_list = ListProperty([])
    night_mode = BooleanProperty(False)

    def on_enter(self):
        self.night_mode = False
        self.load_config()

    def load_config(self):
        cfg = get_config("webdav", {}) or {}
        self.webdav_folder = cfg.get("folder", "")
        self.webdav_user = cfg.get("user", "")
        self.webdav_pwd = cfg.get("pwd", "")
        cd = get_config("cache_dir", {}) or {}
        self.cache_dir = cd.get("v", CACHE_DIR)
        # 自动刷新列表
        if self.webdav_folder:
            self.reload_list()

    def reload_list(self):
        if not self.webdav_folder:
            return
        self.ids.status_label.text = "正在连接..."
        def do_list():
            ok, res = webdav_list_dir(self.webdav_folder, self.webdav_user, self.webdav_pwd)
            Clock.schedule_once(lambda dt: self._on_list_result(ok, res), 0)
        threading.Thread(target=do_list, daemon=True).start()

    def _on_list_result(self, ok, res):
        if not ok:
            self.ids.status_label.text = f"连接失败: {res}"
            return
        self.file_list = res
        self.ids.status_label.text = f"共 {len(res)} 本书" if res else "目录为空"
        Clock.schedule_once(lambda dt: self._build_file_grid(), 0.1)

    def _build_file_grid(self):
        print(f"[DEBUG] _build_file_grid called, file_list len={len(self.file_list)}")
        grid = self.ids.file_grid
        grid.clear_widgets()
        print(f"[DEBUG] file_grid id exists: {hasattr(self.ids, 'file_grid')}")
        for fname, furl in self.file_list:
            btn = Button(
                text=fname,
                size_hint_y=None,
                height=50,
                background_color=(0.2, 0.45, 0.9, 1),
                background_normal="",
                color=(0.95, 0.95, 1, 1),
                font_size="15sp",
                on_press=lambda _, fn=fname, fu=furl: self.open_book(fn, fu)
            )
            grid.add_widget(btn)
        if not self.file_list:
            lbl = Label(
                text="目录为空，请检查 WebDAV 配置",
                size_hint_y=None,
                height=50,
                font_size="14sp",
                color=(0.2, 0.2, 0.2, 1)
            )
            grid.add_widget(lbl)
        # Explicitly set grid height based on children count
        total_children = len(grid.children)
        grid.height = total_children * 50
        print(f"[DEBUG] _build_file_grid done, grid.height={grid.height}, children={total_children}")

    def open_book(self, filename, file_url):
        self.manager.get_screen("reader").load_from_url(
            file_url, filename, self.webdav_user, self.webdav_pwd)
        self.manager.current = "reader"

    def show_reader_settings(self):
        self.manager.current = "reader_settings"

    def show_webdav_settings(self):
        self.manager.current = "webdav_settings"

    def show_sync_settings(self):
        self.manager.current = "sync_settings"


# ========== 阅读偏好设置 ==========
class ReaderSettingsScreen(Screen):
    font_size = NumericProperty(18)
    line_height = NumericProperty(8)
    night_mode = BooleanProperty(False)

    def on_enter(self):
        fs = get_config("font_size", {"v": 18})
        self.font_size = fs.get("v", 18) if isinstance(fs, dict) else 18
        lh = get_config("line_height", {"v": 8})
        self.line_height = lh.get("v", 8) if isinstance(lh, dict) else 8
        nm = get_config("night_mode", {"v": False})
        self.night_mode = nm.get("v", False) if isinstance(nm, dict) else False

    def save(self):
        STORE.put("font_size", v=self.font_size)
        STORE.put("line_height", v=self.line_height)
        STORE.put("night_mode", v=self.night_mode)
        # 同步到 ReaderScreen
        reader = self.manager.get_screen("reader")
        reader.font_size = self.font_size
        reader.line_height = self.line_height
        reader.night_mode = self.night_mode
        reader.apply_theme()
        popup = Popup(title="提示", content=Label(text="已保存"),
                      size_hint=(0.6, 0.3))
        popup.open()
        Clock.schedule_once(lambda dt: setattr(self.manager, 'current', 'bookshelf'), 1)

    def back(self):
        print(f"[DEBUG] back() called, current={self.manager.current}")
        Clock.schedule_once(lambda dt: setattr(self.manager, "current", "bookshelf"), 0.3)


# ========== WebDAV 设置界面 ==========
class WebDAVSettingsScreen(Screen):
    webdav_folder = StringProperty("")
    webdav_user = StringProperty("")
    webdav_pwd = StringProperty("")
    cache_dir = StringProperty(CACHE_DIR)

    def on_enter(self):
        cfg = get_config("webdav", {}) or {}
        self.webdav_folder = cfg.get("folder", "")
        self.webdav_user = cfg.get("user", "")
        self.webdav_pwd = cfg.get("pwd", "")
        cd = get_config("cache_dir", {}) or {}
        self.cache_dir = cd.get("v", CACHE_DIR)

    def save(self):
        STORE.put("webdav", folder=self.webdav_folder, user=self.webdav_user, pwd=self.webdav_pwd)
        STORE.put("cache_dir", v=self.cache_dir)
        popup = Popup(title="提示", content=Label(text="配置已保存"),
                      size_hint=(0.6, 0.3))
        popup.open()
        Clock.schedule_once(lambda dt: setattr(self.manager, 'current', 'bookshelf'), 1)

    def back(self):
        print(f"[DEBUG] back() called, current={self.manager.current}")
        Clock.schedule_once(lambda dt: setattr(self.manager, "current", "bookshelf"), 0.3)


# ========== 进度同步设置（独立 WebDAV）==========
class SyncSettingsScreen(Screen):
    sync_folder = StringProperty("")
    sync_user = StringProperty("")
    sync_pwd = StringProperty("")
    sync_status = StringProperty("")

    def on_enter(self):
        cfg = get_config("sync_webdav", {}) or {}
        self.sync_folder = cfg.get("folder", "")
        self.sync_user = cfg.get("user", "")
        self.sync_pwd = cfg.get("pwd", "")
        self.sync_status = _sync_webdav_status()

    def save(self):
        STORE.put("sync_webdav", folder=self.sync_folder, user=self.sync_user, pwd=self.sync_pwd)
        popup = Popup(title="提示", content=Label(text="配置已保存"),
                      size_hint=(0.6, 0.3))
        popup.open()
        Clock.schedule_once(lambda dt: setattr(self.manager, 'current', 'bookshelf'), 1)

    def sync_now(self):
        def do():
            ok, msg = _sync_pull()
            if not ok:
                ok2, msg2 = _sync_push()
                if not ok2:
                    Clock.schedule_once(lambda dt: self._show_popup(f"同步失败: {msg2}"), 0)
                    return
            Clock.schedule_once(lambda dt: self._show_popup("同步成功"), 0)
        threading.Thread(target=do, daemon=True).start()

    def _show_popup(self, msg):
        popup = Popup(title="同步结果", content=Label(text=msg),
                      size_hint=(0.7, 0.3))
        popup.open()

    def back(self):
        print(f"[DEBUG] back() called, current={self.manager.current}")
        Clock.schedule_once(lambda dt: setattr(self.manager, "current", "bookshelf"), 0.3)


# ========== 独立 WebDAV 同步函数（用 sync_webdav 配置）==========
def _sync_webdav_headers():
    cfg = get_config("sync_webdav", {}) or {}
    if not cfg.get("folder"):
        return None, "未配置同步 WebDAV"
    headers = {}
    user = cfg.get("user", "")
    pwd = cfg.get("pwd", "")
    if user:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return headers, None


def _sync_webdav_url(path):
    cfg = get_config("sync_webdav", {}) or {}
    folder = cfg.get("folder", "").rstrip("/")
    return f"{folder}/{path}"


def _sync_webdav_request(method, url, data=None):
    headers, err = _sync_webdav_headers()
    if err:
        return False, err
    h = dict(headers)
    if data is not None:
        h["Content-Type"] = "application/xml"
    try:
        resp = requests.request(method, url, headers=h, data=data, timeout=15)
        return True, resp.content if resp.status_code != 204 else None
    except Exception as e:
        return False, str(e)


def _sync_webdav_status():
    cfg = get_config("sync_webdav", {}) or {}
    return "已配置" if cfg.get("folder") else "未配置"


def _sync_push():
    cfg = get_config("sync_webdav", {}) or {}
    if not cfg.get("folder"):
        return False, "未配置同步 WebDAV"
    progress_data = {}
    for key in STORE.keys():
        if key.startswith("progress_"):
            try:
                d = STORE.get(key)
                book_url = d.get("url", "")
                if book_url:
                    progress_data[book_url] = d
            except:
                pass
    data = json.dumps(progress_data, ensure_ascii=False).encode("utf-8")
    remote_url = _sync_webdav_url(WEBDAV_PROGRESS_FILE)
    ok, res = _sync_webdav_request("PUT", remote_url, data)
    if ok:
        return True, "上传成功"
    dir_url = remote_url.rsplit("/", 1)[0]
    _sync_webdav_request("MKCOL", dir_url)
    ok2, _ = _sync_webdav_request("PUT", remote_url, data)
    return ok2, "上传成功" if ok2 else str(res)


def _sync_pull():
    cfg = get_config("sync_webdav", {}) or {}
    if not cfg.get("folder"):
        return False, "未配置同步 WebDAV"
    remote_url = _sync_webdav_url(WEBDAV_PROGRESS_FILE)
    ok, data = _sync_webdav_request("GET", remote_url)
    if not ok:
        return False, data
    try:
        remote_progress = json.loads(data.decode("utf-8", errors="replace"))
    except:
        return False, "服务器数据格式错误"
    for book_url, rdata in remote_progress.items():
        key = f"progress_{hashlib.md5(book_url.encode()).hexdigest()[:8]}"
        try:
            local = STORE.get(key) if STORE.exists(key) else {}
        except:
            local = {}
        remote_bm = rdata.get("bookmarks", [])
        local_bm = local.get("bookmarks", [])
        seen = {bm.get("text", "") for bm in remote_bm}
        for bm in local_bm:
            if bm.get("text", "") not in seen:
                rdata.setdefault("bookmarks", []).append(bm)
        STORE.put(key, **rdata)
    return True, "同步成功"


# ========== APP ==========
class JuisReaderApp(App):

    def build(self):
        sm = ScreenManager()
        sm.add_widget(BookshelfScreen(name="bookshelf"))
        sm.add_widget(ReaderScreen(name="reader"))
        sm.add_widget(ReaderSettingsScreen(name="reader_settings"))
        sm.add_widget(WebDAVSettingsScreen(name="webdav_settings"))
        sm.add_widget(SyncSettingsScreen(name="sync_settings"))
        return sm


if __name__ == "__main__":
    # 加载 KV 提前检查错误
    try:
        Builder.load_file(os.path.join(os.path.dirname(__file__), "main.kv"))
    except Exception as e:
        import traceback
        traceback.print_exc()
        input(f"KV 文件加载失败: {e}\n按回车退出...")
        sys.exit(1)

    try:
        JuisReaderApp().run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input(f"运行错误: {e}\n按回车退出...")
