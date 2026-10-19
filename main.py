"""Windows desktop single-pad solder void inspector."""
import json
from io import BytesIO
from zipfile import ZipFile
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox, ttk
import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageTk
from void_analysis import analyze


class Inspector:
    def __init__(self, root):
        self.root = root
        root.title('솔더링 보이드 검사 · 단일 패드')
        root.geometry('1200x850')
        self.image = None
        self.points = []
        self.result = None
        self.closed = False
        self.revision = 0
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.source = ''
        self.threshold = tk.IntVar(value=85)
        self.minimum = tk.StringVar(value='4')
        self.overlay = tk.BooleanVar(value=True)
        self.local = tk.BooleanVar(value=True)
        self.contrast = tk.StringVar(value='8')
        self.radius = tk.StringVar(value='60')
        bar = ttk.Frame(root, padding=12)
        bar.pack(fill='x')
        for label, command in [('이미지 열기', self.open), ('ZIP 열기', self.open_zip), ('데모', self.demo),
                               ('한 점 취소', self.undo), ('패드 다시 지정', self.reset),
                               ('경계 확정', self.close), ('분석 실행', self.run),
                               ('결과 저장', self.save)]:
            ttk.Button(bar, text=label, command=command).pack(side='left', padx=3)
        controls = ttk.Frame(root, padding=12)
        controls.pack(fill='x')
        ttk.Label(controls, text='밝기 임계값 (0~255)').pack(side='left')
        tk.Scale(controls, from_=0, to=255, orient='horizontal', variable=self.threshold,
                 command=lambda _: self.invalidate(), length=250).pack(side='left')
        ttk.Label(controls, text='최소 면적 (px²)').pack(side='left', padx=10)
        ttk.Entry(controls, textvariable=self.minimum, width=8).pack(side='left')
        self.minimum.trace_add('write', lambda *_: self.invalidate())
        ttk.Checkbutton(controls, text='보이드 표시', variable=self.overlay,
                        command=self.draw).pack(side='left', padx=20)
        correction = ttk.Frame(root, padding=12)
        correction.pack(fill='x')
        ttk.Checkbutton(correction, text='동박 음영 보정', variable=self.local,
                        command=self.invalidate).pack(side='left')
        for label, variable in [('주변 대비 밝기 차이 (1~255)', self.contrast),
                                ('배경 반경 (1~250 px)', self.radius)]:
            ttk.Label(correction, text=label).pack(side='left', padx=10)
            ttk.Entry(correction, textvariable=variable, width=6).pack(side='left')
            variable.trace_add('write', lambda *_: self.invalidate())
        ttk.Label(correction, text='보정 ON: 밝기 차이 사용 / OFF: 위 밝기 임계값 사용').pack(side='left', padx=10)
        self.canvas = tk.Canvas(root, bg='#151b25', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=12)
        self.canvas.bind('<Button-1>', self.click)
        self.canvas.bind('<Configure>', lambda _: self.draw())
        self.status = tk.StringVar(value='원본 이미지를 열고 패드 모서리를 순서대로 클릭하세요.')
        ttk.Label(root, textvariable=self.status, padding=12, font=('', 12)).pack(fill='x')
        ttk.Label(root, text='보이드 비율 = 보이드 합계 / 패드 면적 × 100 · 밝은 음영 검출 · '
                  '이미지는 외부로 전송되지 않습니다.\n녹색 표시가 없는 원본을 사용하세요. '
                  '실제 길이 보정 및 합격/불합격 판정은 적용하지 않습니다.', padding=12).pack(fill='x')

    def invalidate(self):
        self.revision += 1
        self.result = None
        if hasattr(self, 'status'):
            self.status.set('설정이 변경되었습니다. 경계 확정 후 분석 실행을 누르세요.')
            self.draw()

    def load(self, image, name):
        self.image = image.convert('RGB')
        self.source = name
        self.reset()
        self.status.set(f'{name} · {image.width} × {image.height} px · 패드 경계를 지정하세요.')

    def open(self):
        name = filedialog.askopenfilename(filetypes=[('이미지', '*.png *.jpg *.jpeg *.bmp *.tif *.tiff'), ('모든 파일', '*.*')])
        if name:
            try:
                with Image.open(name) as im:
                    if im.width * im.height > 20_000_000:
                        raise ValueError('2천만 픽셀 이하 이미지를 사용하세요. 원본에서 패드 주변을 잘라 주세요.')
                    self.load(ImageOps.exif_transpose(im).copy(), name)
            except Exception as error:
                messagebox.showerror('이미지 열기 실패', str(error))

    def demo(self):
        im = Image.new('RGB', (700, 500), '#777777')
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((120, 100, 580, 400), radius=30, fill='#383838')
        for box in [(200, 150, 340, 290), (390, 180, 450, 240), (430, 290, 480, 340)]:
            d.ellipse(box, fill='#b0b0b0')
        self.load(im, '합성 데모 (샘플 사진이 아님)')

    def open_zip(self):
        name = filedialog.askopenfilename(filetypes=[('ZIP 이미지 모음', '*.zip')])
        if not name:
            return
        try:
            with ZipFile(name) as archive:
                members = [i for i in archive.infolist() if not i.is_dir() and
                           i.filename.lower().endswith(('.jpg','.jpeg','.png','.bmp','.tif','.tiff'))]
            if not members:
                raise ValueError('ZIP에 지원하는 이미지가 없습니다.')
        except Exception as error:
            messagebox.showerror('ZIP 열기 실패', str(error))
            return
        window = tk.Toplevel(self.root)
        window.title(f'검사 이미지 선택 · {len(members)}장')
        window.geometry('950x500')
        ttk.Label(window, text='파일을 선택하고 열기를 누르세요. 각 이미지마다 패드 경계를 지정합니다.', padding=10).pack()
        frame = ttk.Frame(window)
        frame.pack(fill='both', expand=True)
        listing = tk.Listbox(frame, exportselection=False)
        scroll = ttk.Scrollbar(frame, command=listing.yview)
        listing.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        listing.pack(fill='both', expand=True)
        for member in members:
            listing.insert('end', member.filename)
        def selected(_=None):
            if not listing.curselection():
                return
            member = members[listing.curselection()[0]]
            try:
                if member.file_size > 50_000_000:
                    raise ValueError('개별 이미지 파일은 50 MB 이하를 사용하세요.')
                with ZipFile(name) as archive:
                    raw = archive.read(member)
                with Image.open(BytesIO(raw)) as im:
                    if im.width * im.height > 20_000_000:
                        raise ValueError('2천만 픽셀 이하 이미지를 사용하세요.')
                    self.load(ImageOps.exif_transpose(im).copy(), name + ' :: ' + member.filename)
            except Exception as error:
                messagebox.showerror('이미지 열기 실패', str(error))
        listing.bind('<Double-Button-1>', selected)
        ttk.Button(window, text='선택 이미지 열기', command=selected).pack(pady=10)

    def reset(self):
        self.points = []
        self.closed = False
        self.invalidate()

    def undo(self):
        if self.points:
            self.points.pop()
        self.closed = False
        self.invalidate()

    def click(self, event):
        if self.image is None or self.closed:
            return
        x, y = (event.x-self.ox)/self.scale, (event.y-self.oy)/self.scale
        if 0 <= x < self.image.width and 0 <= y < self.image.height:
            self.points.append((x, y))
            self.invalidate()
            self.status.set(f'경계 {len(self.points)}점 · 모서리를 순서대로 클릭한 뒤 경계 확정')

    def close(self):
        if len(self.points) < 3:
            messagebox.showinfo('경계 지정', '패드의 모서리를 3점 이상 순서대로 클릭하세요.')
            return
        self.closed = True
        self.draw()
        self.run()

    def run(self):
        if self.future is not None:
            return
        if not self.closed or self.image is None:
            messagebox.showinfo('경계 지정', '패드 경계를 먼저 확정하세요.')
            return
        try:
            minimum = int(self.minimum.get())
            if minimum < 1:
                raise ValueError()
        except ValueError:
            messagebox.showerror('입력 확인', '최소 면적은 1 이상의 정수여야 합니다.')
            return
        revision = self.revision
        try:
            contrast, radius = int(self.contrast.get()), int(self.radius.get())
            if not 1 <= contrast <= 255 or not 1 <= radius <= 250:
                raise ValueError()
        except ValueError:
            messagebox.showerror('입력 확인', '밝기 차이는 1~255, 배경 반경은 1~250의 정수여야 합니다.')
            return
        settings = dict(threshold=self.threshold.get(), minimum=minimum, polygon=list(self.points),
                        mode='local' if self.local.get() else 'absolute',
                        contrast_threshold=contrast, background_radius=radius)
        self.status.set('분석 중…')
        self.future = self.pool.submit(analyze, self.image, **settings)
        def poll():
            if not self.future.done():
                self.root.after(80, poll)
                return
            future, self.future = self.future, None
            try:
                result = future.result()
                if revision != self.revision:
                    return
                self.result = result
                self.settings = settings
                self.status.set(f"보이드 {result['ratio']:.2f}%   |   패드 {result['pad_area']:,} px²   |   "
                                f"보이드 {result['void_area']:,} px²   |   {len(result['sizes'])}개")
                self.draw()
            except Exception as error:
                self.status.set('분석 실패')
                messagebox.showerror('분석 실패', str(error))
        self.root.after(80, poll)

    def draw(self):
        if self.image is None:
            return
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self.scale = min(w/self.image.width, h/self.image.height)
        dw, dh = max(1, round(self.image.width*self.scale)), max(1, round(self.image.height*self.scale))
        self.ox, self.oy = (w-dw)/2, (h-dh)/2
        im = self.image
        if self.result is not None and self.overlay.get():
            rgb = np.array(im)
            rgb[self.result['mask']] = (0, 255, 50)
            im = Image.fromarray(rgb)
        self.photo = ImageTk.PhotoImage(im.resize((dw, dh), Image.Resampling.LANCZOS))
        self.canvas.delete('all')
        self.canvas.create_image(self.ox, self.oy, anchor='nw', image=self.photo)
        coords = [(x*self.scale+self.ox, y*self.scale+self.oy) for x,y in self.points]
        if len(coords) > 1:
            line = coords + ([coords[0]] if self.closed else [])
            self.canvas.create_line(*[v for p in line for v in p], fill='#00ff32', width=2)
        for x,y in coords:
            self.canvas.create_oval(x-3, y-3, x+3, y+3, fill='#00ff32')

    def save(self):
        if self.result is None:
            messagebox.showinfo('결과 저장', '현재 설정으로 먼저 분석하세요.')
            return
        name = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('분석 결과 JSON', '*.json')])
        if name:
            try:
                payload = {k:v for k,v in self.result.items() if k != 'mask'}
                payload.update(source=self.source, image_size=list(self.image.size), **self.settings)
                with open(name, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except OSError as error:
                messagebox.showerror('저장 실패', str(error))


if __name__ == '__main__':
    root = tk.Tk()
    Inspector(root)
    root.mainloop()
