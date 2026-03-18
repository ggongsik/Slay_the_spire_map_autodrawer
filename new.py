"""
AutoDrawer v2 — 획(stroke) 기반 최고속 트레이싱
────────────────────────────────────────────────
핵심 아이디어:
  픽셀마다 클릭(N만 회) → 연결된 획으로 묶어 드래그(수백 회)
  입력 횟수가 100배 이상 줄어들어 속도가 비약적으로 향상됨

파이프라인:
  1. Canny 엣지 추출
  2. Zhang-Suen thinning → 1픽셀 두께 선으로 세선화
  3. DFS로 연결된 픽셀을 획(stroke) 단위로 묶기
  4. Douglas-Peucker 알고리즘으로 획 단순화 (불필요한 중간점 제거)
  5. ctypes SendInput으로 드래그 전송 (가장 빠른 저수준 입력)
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import cv2
import time
import numpy as np
import threading
import urllib.request
import os
import tempfile
import ctypes
import keyboard

# ─────────────────────────────────────────────
#  SendInput 구조체
# ─────────────────────────────────────────────
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

MOUSEEVENTF_MOVE     = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
INPUT_MOUSE          = 0

SCREEN_W = ctypes.windll.user32.GetSystemMetrics(0)
SCREEN_H = ctypes.windll.user32.GetSystemMetrics(1)

def to_norm(x, y):
    return int(x * 65535 / SCREEN_W), int(y * 65535 / SCREEN_H)

def send_move(nx, ny):
    inp = (INPUT * 1)(INPUT(type=INPUT_MOUSE,
        mi=MOUSEINPUT(dx=nx, dy=ny,
                      dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)))
    ctypes.windll.user32.SendInput(1, inp, ctypes.sizeof(INPUT))

def send_down():
    inp = (INPUT * 1)(INPUT(type=INPUT_MOUSE,
        mi=MOUSEINPUT(dwFlags=MOUSEEVENTF_LEFTDOWN)))
    ctypes.windll.user32.SendInput(1, inp, ctypes.sizeof(INPUT))

def send_up():
    inp = (INPUT * 1)(INPUT(type=INPUT_MOUSE,
        mi=MOUSEINPUT(dwFlags=MOUSEEVENTF_LEFTUP)))
    ctypes.windll.user32.SendInput(1, inp, ctypes.sizeof(INPUT))

# ─────────────────────────────────────────────
#  전역 상태
# ─────────────────────────────────────────────
drawing_region = None
stop_flag      = threading.Event()

# ─────────────────────────────────────────────
#  이미지 로드
# ─────────────────────────────────────────────
def load_image_from_file():
    path = filedialog.askopenfilename(
        title="트레이싱할 이미지를 선택하세요",
        filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp")]
    )
    if path:
        entry_path.delete(0, tk.END)
        entry_path.insert(0, path)

def load_image_from_url(url):
    try:
        suffix = ".jpg"
        for ext in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]:
            if url.lower().split("?")[0].endswith(ext):
                suffix = ext
                break
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        urllib.request.urlretrieve(url, tmp.name)
        return tmp.name
    except Exception as e:
        messagebox.showerror("URL 오류", f"다운로드 실패\n{e}")
        return None

def get_image_path():
    raw = entry_path.get().strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        lbl_status.config(text="URL 다운로드 중...", fg="#f0a500")
        root.update()
        return load_image_from_url(raw), True
    return (raw if os.path.exists(raw) else None), False

def cleanup_temp(path, is_temp):
    if is_temp and path and os.path.exists(path):
        try: os.remove(path)
        except: pass

# ─────────────────────────────────────────────
#  드래그로 영역 선택
# ─────────────────────────────────────────────
def start_region_select():
    global drawing_region
    overlay = tk.Toplevel(root)
    overlay.attributes("-fullscreen", True)
    overlay.attributes("-alpha", 0.25)
    overlay.attributes("-topmost", True)
    overlay.configure(bg="black")
    overlay.config(cursor="crosshair")

    canvas = tk.Canvas(overlay, cursor="crosshair", bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    start = {}

    def on_press(e):
        start["x"], start["y"] = e.x_root, e.y_root
        canvas.delete("sel")

    def on_drag(e):
        canvas.delete("sel")
        canvas.create_rectangle(
            start["x"] - overlay.winfo_rootx(),
            start["y"] - overlay.winfo_rooty(),
            e.x, e.y,
            outline="#00ffcc", width=2, fill="#00ffcc",
            stipple="gray25", tags="sel")

    def on_release(e):
        global drawing_region
        x1 = min(start["x"], e.x_root)
        y1 = min(start["y"], e.y_root)
        x2 = max(start["x"], e.x_root)
        y2 = max(start["y"], e.y_root)
        drawing_region = (x1, y1, x2, y2)
        overlay.destroy()
        lbl_region.config(
            text=f"영역: ({x1},{y1})  {x2-x1}×{y2-y1}px", fg="#00ffcc")

    canvas.bind("<ButtonPress-1>",   on_press)
    canvas.bind("<B1-Motion>",       on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    overlay.bind("<Escape>",         lambda e: overlay.destroy())
    lbl_status.config(text="드래그로 영역 선택 (ESC: 취소)", fg="#aaaaaa")

# ─────────────────────────────────────────────
#  획(stroke) 추출 엔진
# ─────────────────────────────────────────────
# 8방향 이웃
DIR8 = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]

def extract_strokes(edges):
    """
    Greedy nearest neighbor 방식으로 획 추출.
    현재 픽셀에서 가장 가까운 미방문 이웃을 따라가므로
    픽셀이 연속적으로 연결되어 끊김 없는 획이 생성됨.
    """
    h, w = edges.shape
    visited = np.zeros((h, w), dtype=bool)
    strokes = []

    ys, xs = np.where(edges > 0)
    if len(ys) == 0:
        return strokes

    # 끝점(이웃 1개 이하)부터 시작하면 획이 더 자연스러움
    def neighbor_pixels(y, x):
        result = []
        for dy, dx in DIR8:
            ny, nx = y+dy, x+dx
            if 0 <= ny < h and 0 <= nx < w and edges[ny, nx] and not visited[ny, nx]:
                result.append((ny, nx))
        return result

    def neighbor_count_unvisited(y, x):
        return len(neighbor_pixels(y, x))

    # 시작점 우선순위: 끝점(이웃 1개) → 일반점
    endpoints = []
    others    = []
    for y, x in zip(ys, xs):
        cnt = 0
        for dy, dx in DIR8:
            ny, nx = y+dy, x+dx
            if 0 <= ny < h and 0 <= nx < w and edges[ny, nx]:
                cnt += 1
        if cnt <= 1:
            endpoints.append((y, x))
        else:
            others.append((y, x))

    all_starts = endpoints + others

    for sy, sx in all_starts:
        if visited[sy, sx]:
            continue

        stroke = []
        cy, cx = sy, sx

        while True:
            if visited[cy, cx]:
                break
            visited[cy, cx] = True
            stroke.append((cx, cy))  # (x, y)

            neighbors = neighbor_pixels(cy, cx)
            if not neighbors:
                break

            # 가장 가까운 이웃 선택 (대각선보다 직선 우선)
            # 직선 이웃(상하좌우) 있으면 우선 선택
            straight = [(ny, nx) for ny, nx in neighbors
                        if ny == cy or nx == cx]
            if straight:
                cy, cx = straight[0]
            else:
                cy, cx = neighbors[0]

        if len(stroke) >= 1:
            strokes.append(stroke)

    return strokes


def simplify_stroke(stroke, epsilon=1.0):
    """
    Douglas-Peucker 알고리즘으로 획의 중간점 제거.
    epsilon이 클수록 더 많이 단순화 (드래그 횟수 감소, 정밀도 감소)
    """
    if len(stroke) <= 2:
        return stroke
    pts = np.array(stroke, dtype=np.float32)
    # cv2.approxPolyDP는 (N,1,2) 형태 필요
    approx = cv2.approxPolyDP(pts.reshape(-1,1,2), epsilon, False)
    return [tuple(p[0]) for p in approx]


# ─────────────────────────────────────────────
#  트레이싱 실행
# ─────────────────────────────────────────────
def run_tracing():
    global drawing_region

    image_path, is_temp = get_image_path()
    if not image_path:
        messagebox.showwarning("경고", "이미지 경로/URL을 입력하세요.")
        return
    if drawing_region is None:
        messagebox.showwarning("경고", "먼저 영역을 선택하세요.")
        cleanup_temp(image_path, is_temp)
        return

    # 한글 경로 대응
    with open(image_path, 'rb') as f:
        buf = np.frombuffer(f.read(), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if img is None:
        messagebox.showerror("오류", "이미지를 읽을 수 없습니다.")
        cleanup_temp(image_path, is_temp)
        return

    x1, y1, x2, y2 = drawing_region
    target_w = max(x2 - x1, 10)
    target_h = max(y2 - y1, 10)
    orig_h, orig_w = img.shape[:2]

    lbl_status.config(text="엣지 추출 중...", fg="#f0a500")
    root.update()

    t1v = int(slider_t1.get())
    t2v = int(slider_t2.get())

    # 가우시안 블러로 노이즈 제거 후 Canny
    blurred = cv2.GaussianBlur(img, (3, 3), 0)
    edges   = cv2.Canny(blurred, t1v, t2v)

    # 세선화: 1픽셀 두께로 만들어 획 수 최소화
    try:
        edges = cv2.ximgproc.thinning(edges)  # opencv-contrib 필요
    except AttributeError:
        kernel = np.ones((2,2), np.uint8)
        edges  = cv2.erode(edges, kernel, iterations=1)

    # target 크기로 리사이즈 (엣지 추출 후 리사이즈)
    edges = cv2.resize(edges, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
    edges = (edges > 127).astype(np.uint8) * 255

    lbl_status.config(text="획 추출 중...", fg="#f0a500")
    root.update()

    strokes = extract_strokes(edges)

    # Douglas-Peucker 단순화
    epsilon = float(spin_epsilon.get())
    strokes = [simplify_stroke(s, epsilon) for s in strokes]
    strokes = [s for s in strokes if len(s) >= 1]

    total_strokes = len(strokes)
    total_points  = sum(len(s) for s in strokes)
    lbl_status.config(
        text=f"획 {total_strokes}개 / 점 {total_points}개. {int(spin_delay.get())}초 후 시작...",
        fg="#f0a500")
    root.update()

    delay_sec = int(spin_delay.get())
    for i in range(delay_sec, 0, -1):
        lbl_status.config(text=f"{i}초 후 시작...", fg="#f0a500")
        root.update()
        time.sleep(1)

    lbl_status.config(text="트레이싱 중... (ESC: 중단)", fg="#ff4444")
    root.update()

    pt_delay  = float(spin_pt_delay.get())   # 획 내 점간 딜레이
    str_delay = float(spin_str_delay.get())  # 획과 획 사이 딜레이

    stop_flag.clear()
    keyboard.add_hotkey("esc", stop_flag.set)

    try:
        # 획과 획 사이 이동 시 캔버스 밖으로 마우스를 빼서
        # 그림판이 이동 경로에 점 찍는 것 방지
        safe_nx, safe_ny = to_norm(0, 0)  # 화면 왼쪽 상단 모서리 (안전지대)

        for stroke in strokes:
            if stop_flag.is_set():
                send_up()
                lbl_status.config(text="⛔ ESC 중단", fg="#ff4444")
                return

            if len(stroke) == 1:
                px, py = stroke[0]
                ax, ay = x1 + int(px), y1 + int(py)
                nx, ny = to_norm(ax, ay)
                send_move(nx, ny)
                send_down()
                send_up()
            else:
                # 다음 획 시작 전 안전지대로 이동 (마우스 UP 상태)
                send_move(safe_nx, safe_ny)

                px, py = stroke[0]
                ax, ay = x1 + int(px), y1 + int(py)
                nx, ny = to_norm(ax, ay)
                send_move(nx, ny)
                send_down()

                for px, py in stroke[1:]:
                    if stop_flag.is_set():
                        break
                    ax, ay = x1 + int(px), y1 + int(py)
                    nx, ny = to_norm(ax, ay)
                    send_move(nx, ny)
                    if pt_delay > 0:
                        time.sleep(pt_delay)

                send_up()

            if str_delay > 0:
                time.sleep(str_delay)

        lbl_status.config(text="✅ 완료!", fg="#00ffcc")
    except Exception as e:
        lbl_status.config(text=f"⛔ 오류: {e}", fg="#ff4444")
    finally:
        keyboard.remove_hotkey("esc")
        stop_flag.clear()
        cleanup_temp(image_path, is_temp)

def start_thread():
    threading.Thread(target=run_tracing, daemon=True).start()

# ─────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────
root = tk.Tk()
root.title("AutoDrawer v2")
root.resizable(False, False)
root.configure(bg="#1a1a2e")

FONT_TITLE  = ("Consolas", 15, "bold")
FONT_LABEL  = ("Consolas", 9)
FONT_BUTTON = ("Consolas", 10, "bold")
BG   = "#1a1a2e"
FG   = "#e0e0e0"
ACC  = "#00ffcc"
BTN2 = "#0f3460"

def section(parent, text):
    f = tk.Frame(parent, bg=BG)
    tk.Label(f, text=text, font=("Consolas", 9, "bold"), bg=BG, fg=ACC).pack(anchor="w")
    tk.Frame(f, bg=ACC, height=1).pack(fill=tk.X, pady=(1,6))
    return f

tk.Label(root, text="◈  AUTO DRAWER  v2", font=FONT_TITLE,
         bg=BG, fg=ACC).pack(padx=16, pady=6, anchor="w")

# 이미지 경로
sec1 = section(root, "  이미지 경로 / URL")
sec1.pack(fill=tk.X, padx=16, pady=(4,0))
frm = tk.Frame(sec1, bg=BG)
frm.pack(fill=tk.X)
entry_path = tk.Entry(frm, width=42, bg="#0d0d1a", fg=FG,
                      insertbackground=FG, relief=tk.FLAT, font=FONT_LABEL)
entry_path.pack(side=tk.LEFT, ipady=4, padx=(0,6))
tk.Button(frm, text="파일 선택", font=FONT_BUTTON, bg=BTN2, fg=FG,
          relief=tk.FLAT, cursor="hand2",
          activebackground=ACC, activeforeground=BG,
          command=load_image_from_file).pack(side=tk.LEFT)

# 영역 선택
sec2 = section(root, "  그리기 영역")
sec2.pack(fill=tk.X, padx=16, pady=(8,0))
tk.Button(sec2, text="🖱  드래그로 영역 선택", font=FONT_BUTTON, bg=BTN2, fg=FG,
          relief=tk.FLAT, cursor="hand2",
          activebackground=ACC, activeforeground=BG,
          command=start_region_select).pack(anchor="w")
lbl_region = tk.Label(sec2, text="영역이 선택되지 않았습니다.",
                      font=FONT_LABEL, bg=BG, fg="#666688")
lbl_region.pack(anchor="w", pady=(2,0))

# 엣지 민감도
sec3 = section(root, "  엣지 민감도")
sec3.pack(fill=tk.X, padx=16, pady=(8,0))

def make_slider(parent, label, from_, to, default):
    f = tk.Frame(parent, bg=BG)
    f.pack(fill=tk.X, pady=1)
    tk.Label(f, text=label, width=12, anchor="w",
             font=FONT_LABEL, bg=BG, fg=FG).pack(side=tk.LEFT)
    s = tk.Scale(f, from_=from_, to=to, orient=tk.HORIZONTAL,
                 length=200, bg=BG, fg=FG, troughcolor=BTN2,
                 highlightthickness=0, font=FONT_LABEL, activebackground=ACC)
    s.set(default)
    s.pack(side=tk.LEFT)
    return s

slider_t1 = make_slider(sec3, "Threshold 1", 0, 300, 100)
slider_t2 = make_slider(sec3, "Threshold 2", 0, 500, 200)

# 속도/품질 설정
sec4 = section(root, "  속도 / 품질")
sec4.pack(fill=tk.X, padx=16, pady=(8,0))

def spin_row(parent, label, default, from_, to, inc, tip):
    f = tk.Frame(parent, bg=BG)
    f.pack(fill=tk.X, pady=2)
    tk.Label(f, text=label, width=18, anchor="w",
             font=FONT_LABEL, bg=BG, fg=FG).pack(side=tk.LEFT)
    sv = tk.StringVar(value=str(default))
    tk.Spinbox(f, from_=from_, to=to, increment=inc, textvariable=sv, width=7,
               bg="#0d0d1a", fg=FG, buttonbackground=BTN2,
               relief=tk.FLAT, font=FONT_LABEL).pack(side=tk.LEFT, padx=(0,8))
    tk.Label(f, text=tip, font=("Consolas", 8),
             bg=BG, fg="#556677").pack(side=tk.LEFT)
    return sv

spin_delay    = spin_row(sec4, "시작 대기(초)",    5,    1,   30, 1,
                         "시작 전 준비 시간")
spin_epsilon  = spin_row(sec4, "획 단순화",        1.0,  0.0,  10, 0.5,
                         "클수록 빠름, 작을수록 정밀")
spin_pt_delay = spin_row(sec4, "점간 딜레이(초)",  0.0,  0.0,  0.1, 0.001,
                         "획 내 점 사이 딜레이")
spin_str_delay= spin_row(sec4, "획간 딜레이(초)",  0.01, 0.0,  0.5, 0.005,
                         "획과 획 사이 딜레이 (렌더링 여유)")

# 시작 버튼
tk.Frame(root, bg=ACC, height=1).pack(fill=tk.X, padx=16, pady=(12,0))
tk.Button(root, text="▶  트레이싱 시작 (v2)",
          font=("Consolas", 12, "bold"),
          bg=ACC, fg=BG, relief=tk.FLAT, cursor="hand2",
          activebackground="#00ccaa", activeforeground=BG,
          pady=8, command=start_thread).pack(fill=tk.X, padx=16, pady=8)

lbl_status = tk.Label(root, text="준비 완료", font=FONT_LABEL, bg=BG, fg="#556677")
lbl_status.pack(pady=(0,10))

root.mainloop()