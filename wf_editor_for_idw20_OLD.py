import os, io, json, zipfile, math, datetime, shutil
from tkinter import Tk, Canvas, Frame, Button, filedialog, Label, Entry, StringVar, IntVar, DoubleVar, Checkbutton, Toplevel, ttk, messagebox, Text, Scrollbar
from PIL import Image, ImageTk, ImageOps, ImageFont, ImageDraw

APP_TITLE = "Wf Editor for IDW20"
VERSION = "0.10.0"
AUTHOR = "CoolSteel712"

# Updated canvas resolution for IDW20
CANVAS_W, CANVAS_H = 320, 385

class AssetManager:
    def __init__(self):
        self.images = {}  # name -> PIL Image
        self.fonts = {}   # name -> font data

    def load_image(self, name_or_path):
        # If absolute path, use it; else assume relative to CWD
        path = name_or_path
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        if not os.path.exists(path):
            # Try just the basename in current dir
            base = os.path.basename(path)
            if os.path.exists(base):
                path = base
            else:
                raise FileNotFoundError(f"Asset not found: {name_or_path}")
        img = Image.open(path).convert("RGBA")
        self.images[name_or_path] = img
        return img

    def get(self, key):
        return self.images.get(key)
    
    def load_font_json(self, path):
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        if not os.path.exists(path):
            base = os.path.basename(path)
            if os.path.exists(base):
                path = base
            else:
                raise FileNotFoundError(f"Font JSON not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            font_data = json.load(f)
        
        # Handle both array and dictionary formats
        if isinstance(font_data, list):
            # Convert array format to dictionary
            converted_data = {}
            for item in font_data:
                if isinstance(item, dict) and "name" in item:
                    converted_data[item["name"]] = item
            font_data = converted_data
        elif isinstance(font_data, dict) and "item" in font_data and isinstance(font_data["item"], list):
            # Handle the case where fonts are in an "item" array
            converted_data = {}
            for item in font_data["item"]:
                if isinstance(item, dict) and "name" in item:
                    converted_data[item["name"]] = item
            font_data = converted_data
        
        self.fonts[path] = font_data
        return font_data

class WatchFaceModel:
    def __init__(self):
        self.data = {
            "version": 1,
            "clouddialversion": 3,
            "preview": "preview.png",
            "name": "customiwf",
            "author": "you",
            "description": "IDW20",
            "deviceId": "IDW20",
            "bluetooth": False,
            "disturb": False,
            "battery": False,
            "compress": "LZ4",
            "environment": "Production",
            "item": [],
            "bkground": "files0.png"
        }
        self.assets = AssetManager()
        self.font_json_path = None
        self.font_data = {"item": []}  # Initialize with empty font data

    # === JSON/IWF ===
    def load_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def save_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)
    
    # === Font JSON ===
    def save_font_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            # Compact format for font.json (no spaces)
            json.dump(self.font_data, f, ensure_ascii=False, separators=(',', ':'))

class Renderer:
    def __init__(self, model: WatchFaceModel):
        self.m = model
        self.widget_values = {
            "time": "10:08",
            "date": "09/21",
            "week": "TUE",
            "day": "21",
            "second": "36",
            "hour": "10",
            "min": "08",
            "year": "2023",
            "heartrate": "128",
            "calorie": "327",
            "distance": "10.22",
            "step": "16772",
            "battery": "85%",
            "weather": "25oC",
            "apm": "PM"
        }

    def update_widget_value(self, widget_type, value):
        """Update a specific widget's preview value"""
        if widget_type in self.widget_values:
            self.widget_values[widget_type] = str(value)
            return True
        return False

    def _paste_centered(self, base, img, anchorx, anchory, centerx, centery, angle=0):
        # Rotate around the image's local center (centerx,centery) then paste so that
        # the anchor on the canvas aligns with that pivot.
        # Create a canvas big enough to hold rotation without cropping
        ox, oy = int(centerx), int(centery)
        # Create offset so pivot is at the center for rotation
        # Place original image onto a larger canvas so that (ox,oy) becomes the center
        w, h = img.size
        pad_left = max(ox, w-ox)
        pad_top  = max(oy, h-oy)
        big_w, big_h = pad_left + pad_left, pad_top + pad_top
        big = Image.new("RGBA", (big_w, big_h), (0,0,0,0))
        paste_x = pad_left - ox
        paste_y = pad_top - oy
        big.paste(img, (paste_x, paste_y), img)
        rot = big.rotate(-angle, resample=Image.BICUBIC, expand=True)
        # Now paste so that the center of rot equals (anchorx,anchory)
        rx, ry = rot.size
        pos = (int(anchorx - rx/2), int(anchory - ry/2))
        base.alpha_composite(rot, dest=pos)

    def _render_digit_widget(self, canvas, item, value):
        """Render a widget using individual digit PNGs"""
        try:
            widget_type = item.get("type")
            x, y = item.get("x", 0), item.get("y", 0)
            w, h = item.get("w", 0), item.get("h", 0)
            align = item.get("align", "left")
            
            # Get the value to display
            if widget_type in self.widget_values:
                value_str = str(self.widget_values[widget_type])
            else:
                value_str = "0"
            
            # Get font information
            font_name = item.get("font", "")
            
            # Load digit images
            digit_images = {}
            
            # Try multiple folder locations:
            # 1. widgets/[widget_type]/[font_name]/ (new structure)
            # 2. widgets/[widget_type]/ (old structure)
            # 3. fonts/[font_name]/ (C++ app structure for compatibility)
            
            possible_paths = [
                os.path.join("widgets", widget_type, font_name),
                os.path.join("widgets", widget_type),
                os.path.join("fonts", font_name),
                font_name  # Just the font name itself
            ]
            
            digits_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    digits_path = path
                    break
            
            if digits_path and os.path.exists(digits_path):
                # Load digits 0-9
                for digit in "0123456789":
                    # Try multiple filename variations
                    possible_files = [
                        os.path.join(digits_path, f"{digit}.png"),
                        os.path.join(digits_path, f"{digit}.PNG"),
                        os.path.join(digits_path, digit.upper() + ".png"),
                        os.path.join(digits_path, digit.upper() + ".PNG"),
                    ]
                    
                    for digit_file in possible_files:
                        if os.path.exists(digit_file):
                            try:
                                digit_images[digit] = self.m.assets.load_image(digit_file)
                                break
                            except:
                                continue
                
                # Also load special characters if they exist
                special_chars = {
                    "colon": ":",
                    "slash": "/",
                    "degree": "o",
                    "percent": "%",
                    "C": "C",
                    "F": "F",
                    "AM": "AM",
                    "PM": "PM",
                    "period": ".",
                    "A": "A",
                    "P": "P",
                    "M": "M",
                    "dash": "-"
                }
                
                for char_name, char_value in special_chars.items():
                    # Try multiple filename variations
                    possible_files = [
                        os.path.join(digits_path, f"{char_name}.png"),
                        os.path.join(digits_path, f"{char_name}.PNG"),
                        os.path.join(digits_path, char_name.upper() + ".png"),
                        os.path.join(digits_path, char_name.upper() + ".PNG"),
                    ]
                    
                    for char_file in possible_files:
                        if os.path.exists(char_file):
                            try:
                                digit_images[char_value] = self.m.assets.load_image(char_file)
                                break
                            except:
                                continue
            
                # Calculate total width
                total_width = 0
                char_widths = []
                for char in value_str:
                    if char in digit_images:
                        img = digit_images[char]
                        total_width += img.width
                        char_widths.append(img.width)
                    else:
                        # Default width for missing characters
                        total_width += 10
                        char_widths.append(10)
                
                # Calculate starting position based on alignment
                current_x = x
                if align == "center":
                    current_x = x + (w - total_width) // 2
                elif align == "right":
                    current_x = x + w - total_width
                
                # Render each character
                for char in value_str:
                    if char in digit_images:
                        img = digit_images[char]
                        canvas.alpha_composite(img, (current_x, y))
                        current_x += img.width
                    else:
                        # If no image for this character, skip it
                        current_x += 10  # Default width for missing characters
            
        except Exception as e:
            print(f"Error rendering {widget_type} widget: {e}")

    def render(self, when: datetime.time, multimeter_values=None):
        W, H = CANVAS_W, CANVAS_H
        canvas = Image.new("RGBA", (W, H), (0,0,0,0))
        d = self.m.data
        # background
        if d.get("bkground"):
            try:
                bg = self.m.assets.load_image(d["bkground"])
                bg = bg.resize((W,H), Image.BICUBIC)
                canvas.alpha_composite(bg)
            except Exception as e:
                pass

        # Update time widgets based on custom time
        if when:
            # Update time components
            hour_str = str(when.hour).zfill(2)
            min_str = str(when.minute).zfill(2)
            sec_str = str(when.second).zfill(2)
            
            # Format time as HH:MM
            time_str = f"{hour_str}:{min_str}"
            
            # Update widget values
            self.widget_values["time"] = time_str
            self.widget_values["hour"] = hour_str
            self.widget_values["min"] = min_str
            self.widget_values["second"] = sec_str
            self.widget_values["apm"] = "PM" if when.hour >= 12 else "AM"

        # widgets/items
        for it in d.get("item", []):
            wtype = (it.get("widget"), it.get("type"))
            
            # Handle digit-based widgets
            if it.get("widget") == "custom" and it.get("type") in ["time", "date", "week", "day", "second", 
                                                                  "hour", "min", "year", "heartrate", 
                                                                  "calorie", "distance", "step", "battery", 
                                                                  "weather", "apm"]:
                self._render_digit_widget(canvas, it, self.widget_values.get(it.get("type"), ""))
            
            # Handle watch hands
            elif wtype == ("watch","time"):
                hour_img = it.get("hour")
                min_img  = it.get("minute")
                sec_img  = it.get("second")
                # hour
                if hour_img:
                    img = self.m.assets.load_image(hour_img)
                    cx, cy = it.get("hourcenterx", img.size[0]//2), it.get("hourcentery", img.size[1]//2)
                    ax, ay = it.get("houranchorx", W//2), it.get("houranchory", H//2)
                    angle = (when.hour%12 + when.minute/60.0) * 30.0
                    self._paste_centered(canvas, img, ax, ay, cx, cy, angle)
                # minute
                if min_img:
                    img = self.m.assets.load_image(min_img)
                    cx, cy = it.get("mincenterx", img.size[0]//2), it.get("mincentery", img.size[1]//2)
                    ax, ay = it.get("minanchorx", W//2), it.get("minanchory", H//2)
                    angle = (when.minute + when.second/60.0) * 6.0
                    self._paste_centered(canvas, img, ax, ay, cx, cy, angle)
                # second
                if sec_img:
                    img = self.m.assets.load_image(sec_img)
                    cx, cy = it.get("seccenterx", img.size[0]//2), it.get("seccentery", img.size[1]//2)
                    ax, ay = it.get("secanchorx", W//2), it.get("secanchory", H//2)
                    angle = (when.second) * 6.0
                    self._paste_centered(canvas, img, ax, ay, cx, cy, angle)

        return canvas

class App:
    def __init__(self, root):
        root.title(APP_TITLE)
        self.root = root
        self.model = WatchFaceModel()
        self.renderer = Renderer(self.model)

        # UI
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        
        # Preview tab
        preview_frame = Frame(self.notebook)
        self.notebook.add(preview_frame, text="Preview")
        
        # Editor tab
        editor_frame = Frame(self.notebook)
        self.notebook.add(editor_frame, text="Editor")
        
        # About tab
        about_frame = Frame(self.notebook)
        self.notebook.add(about_frame, text="About")

        # Preview tab content
        left = Frame(preview_frame)
        left.pack(side="left", padx=8)

        right = Frame(preview_frame)
        right.pack(side="left", fill="both", expand=True)

        self.canvas = Canvas(left, width=CANVAS_W, height=CANVAS_H, bg="#111")
        self.canvas.pack()

        # Time controls
        time_frame = Frame(left)
        time_frame.pack(pady=(10, 0))
        
        Label(time_frame, text="Custom Time:").grid(row=0, column=0, columnspan=2, pady=(0, 5))
        
        # Time entry fields
        self.hour_var = StringVar(value="10")
        self.minute_var = StringVar(value="08")
        self.second_var = StringVar(value="36")
        
        Label(time_frame, text="Hours:").grid(row=1, column=0, sticky="e", padx=(0, 2))
        Entry(time_frame, textvariable=self.hour_var, width=3).grid(row=1, column=1, padx=(0, 10))
        
        Label(time_frame, text="Minutes:").grid(row=1, column=2, sticky="e", padx=(0, 2))
        Entry(time_frame, textvariable=self.minute_var, width=3).grid(row=1, column=3, padx=(0, 10))
        
        Label(time_frame, text="Seconds:").grid(row=1, column=4, sticky="e", padx=(0, 2))
        Entry(time_frame, textvariable=self.second_var, width=3).grid(row=1, column=5)
        
        # Apply time button
        Button(time_frame, text="Apply Time", command=self.on_apply_custom_time).grid(row=2, column=0, columnspan=6, pady=(5, 0))

        # Widget preview controls
        preview_control_frame = Frame(left)
        preview_control_frame.pack(pady=(10, 0))
        
        Label(preview_control_frame, text="Widget Preview Values:").pack(anchor="w", pady=(0, 5))
        
        # Widget selection and value entry
        control_grid = Frame(preview_control_frame)
        control_grid.pack(fill="x")
        
        Label(control_grid, text="Widget:").grid(row=0, column=0, sticky="e", padx=(0, 5))
        self.preview_widget_type = StringVar(value="heartrate")
        widget_options = ["heartrate", "step", "calorie", "distance", "battery", "weather", 
                         "date", "week", "day", "year", "apm"]
        widget_dropdown = ttk.Combobox(control_grid, textvariable=self.preview_widget_type, 
                                       values=widget_options, state="readonly", width=10)
        widget_dropdown.grid(row=0, column=1, padx=(0, 10))
        
        Label(control_grid, text="Value:").grid(row=0, column=2, sticky="e", padx=(0, 5))
        self.preview_widget_value = StringVar(value="128")
        Entry(control_grid, textvariable=self.preview_widget_value, width=10).grid(row=0, column=3)
        
        Button(control_grid, text="Update", command=self.on_update_widget_preview).grid(row=0, column=4, padx=(10, 0))

        # Buttons
        btns = Frame(left)
        btns.pack(pady=10)
        Button(btns, text="Load iwf.json", command=self.on_load_json).grid(row=0, column=0, padx=4, pady=2)
        Button(btns, text="Save iwf.json", command=self.on_save_json).grid(row=0, column=1, padx=4, pady=2)
        Button(btns, text="Save Preview", command=self.on_save_preview).grid(row=1, column=0, padx=4, pady=2)
        Button(btns, text="Add Background", command=self.on_add_bg).grid(row=1, column=1, padx=4, pady=2)
        Button(btns, text="Add Clock Hands", command=self.on_add_hands).grid(row=2, column=0, columnspan=2, padx=4, pady=2)
        Button(btns, text="???", command=self.on_unknown).grid(row=3, column=0, columnspan=2, padx=4, pady=2)

        # Info
        Label(right, text="iwf.json tree").pack(anchor="w")
        self.tree = ttk.Treeview(right, columns=("value",), show="tree")
        self.tree.pack(fill="both", expand=True, pady=(6,6))
        # Make tree editable
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # Editor tab content
        editor_left = Frame(editor_frame)
        editor_left.pack(side="left", fill="y", padx=8, pady=8)
        
        editor_right = Frame(editor_frame)
        editor_right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        
        # Left side - Widget controls
        widget_frame = Frame(editor_left)
        widget_frame.pack(fill="x", pady=(0, 20))
        
        Label(widget_frame, text="Add Custom Widget (More soon)").pack(anchor="w", pady=(0, 5))
        
        self.widget_type = StringVar(value="time")
        widget_options = ["time", "date", "week", "day", "second", "hour", "min", "year", 
                         "heartrate", "calorie", "distance", "step", "battery", "weather", "apm"]
        widget_dropdown = ttk.Combobox(widget_frame, textvariable=self.widget_type, values=widget_options, state="readonly")
        widget_dropdown.pack(fill="x", pady=(0, 10))
        
        Button(widget_frame, text="Add Selected Widget", command=self.on_add_widget).pack(pady=(0, 10))
        
        Button(widget_frame, text="Remove Selected Widget", command=self.on_remove_widget).pack(pady=(0, 20))
        
        # Left side - Font JSON controls
        font_frame = Frame(editor_left)
        font_frame.pack(fill="x")
        
        Label(font_frame, text="font.json").pack(anchor="w", pady=(0, 5))
        
        Button(font_frame, text="Save font.json", command=self.on_save_font_json).pack(fill="x", pady=(0, 5))
        
        # Right side - JSON editors with notebook
        json_notebook = ttk.Notebook(editor_right)
        json_notebook.pack(fill="both", expand=True)
        
        # iwf.json editor tab
        iwf_frame = Frame(json_notebook)
        json_notebook.add(iwf_frame, text="iwf.json")
        
        Label(iwf_frame, text="Raw iwf.json editor").pack(anchor="w")
        
        iwf_text_frame = Frame(iwf_frame)
        iwf_text_frame.pack(fill="both", expand=True, pady=(5, 0))
        
        self.json_text = Text(iwf_text_frame, wrap="word")
        iwf_scrollbar = Scrollbar(iwf_text_frame, orient="vertical", command=self.json_text.yview)
        self.json_text.configure(yscrollcommand=iwf_scrollbar.set)
        
        self.json_text.pack(side="left", fill="both", expand=True)
        iwf_scrollbar.pack(side="right", fill="y")
        
        Button(iwf_frame, text="Apply IWF.JSON Changes", command=self.on_apply_json).pack(pady=(10, 0))
        
        # font.json editor tab
        font_editor_frame = Frame(json_notebook)
        json_notebook.add(font_editor_frame, text="font.json")
        
        Label(font_editor_frame, text="Raw font.json editor").pack(anchor="w")
        
        font_text_frame = Frame(font_editor_frame)
        font_text_frame.pack(fill="both", expand=True, pady=(5, 0))
        
        self.font_json_text = Text(font_text_frame, wrap="word")
        font_scrollbar = Scrollbar(font_text_frame, orient="vertical", command=self.font_json_text.yview)
        self.font_json_text.configure(yscrollcommand=font_scrollbar.set)
        
        self.font_json_text.pack(side="left", fill="both", expand=True)
        font_scrollbar.pack(side="right", fill="y")
        
        Button(font_editor_frame, text="Apply FONT.JSON Changes", command=self.on_apply_font_json).pack(pady=(10, 0))
        
        # About tab content
        about_text = Text(about_frame, wrap="word", height=10, width=50)
        about_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        about_info = f"""About the wf editor for IDW20

Version: {VERSION}
Made by: {AUTHOR}

This tool allows you to create and edit watch faces for the IDW20 using the .iwf format.

Made with creativity and passion by CoolSteel712.
"""
        
        about_text.insert("1.0", about_info)
        about_text.config(state="disabled")

    def on_tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        col = self.tree.identify_column(event.x)
        if col != "#0":
            return
        text = self.tree.item(item_id, "text")
        if ": " not in text:
            return
        key, value = text.split(": ", 1)
        x, y, w, h = self.tree.bbox(item_id, column=col)
        entry = Entry(self.tree)
        entry.insert(0, value)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()

        def save_edit(event=None):
            new_val = entry.get()
            entry.destroy()
            # update model data
            self._update_model_from_tree_path(item_id, key.strip(), new_val)
            self.refresh_tree()
            self.update_preview()

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)

    
    def _update_model_from_tree_path(self, item_id, key, new_val):
        # trace back parents to find path in self.model.data
        path_keys = []
        cur_id = item_id
        while cur_id:
            text = self.tree.item(cur_id, "text")
            if ": " in text:
                pk, pv = text.split(": ", 1)
                pk = pk.strip()
            else:
                pk = text.strip()
            if pk.endswith(":"):
                pk = pk[:-1].strip()
            # for nodes like "0: watch/time", take only number part
            if pk.isdigit() is False and pk.split()[0].isdigit():
                pk = pk.split()[0]
            path_keys.append(pk)
            cur_id = self.tree.parent(cur_id)
        path_keys = list(reversed(path_keys))

        # navigate in model.data
        obj = self.model.data
        try:
            for pk in path_keys[1:-1]:  # skip the very first root label
                if isinstance(obj, list) and pk.isdigit():
                    obj = obj[int(pk)]
                elif pk in obj:
                    obj = obj[pk]
                elif pk.isdigit():
                    obj = obj[int(pk)]
                else:
                    # try force conversion if possible
                    try:
                        idx = int(pk)
                        obj = obj[idx]
                    except:
                        raise KeyError(f"Invalid path key: {pk}")
            # attempt type conversion for new_val
            if new_val.isdigit():
                new_val_conv = int(new_val)
            else:
                try:
                    new_val_conv = float(new_val)
                except:
                    if new_val.lower() in ("true", "false"):
                        new_val_conv = new_val.lower() == "true"
                    else:
                        new_val_conv = new_val
            obj[key] = new_val_conv
        except Exception as e:
            print("Failed to update model path", path_keys, e)

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        d = self.model.data
        root_id = self.tree.insert("", "end", text=f'name: {d.get("name")}')
        self.tree.insert(root_id, "end", text=f'author: {d.get("author")}')
        self.tree.insert(root_id, "end", text=f'deviceId: {d.get("deviceId")}')
        self.tree.insert(root_id, "end", text=f'clouddialversion: {d.get("clouddialversion")}')
        self.tree.insert(root_id, "end", text=f'preview: {d.get("preview")}')
        self.tree.insert(root_id, "end", text=f'bkground: {d.get("bkground")}')
        items = self.tree.insert(root_id, "end", text="item:")
        for i, it in enumerate(d.get("item", [])):
            label = f'{i}: {it.get("widget")}/{it.get("type")}'
            it_id = self.tree.insert(items, "end", text=label)
            for k,v in it.items():
                self.tree.insert(it_id, "end", text=f"{k}: {v}")
        self.tree.item(root_id, open=True)
        self.tree.item(items, open=True)
        
        # Update JSON editor
        self.json_text.delete(1.0, "end")
        self.json_text.insert(1.0, json.dumps(self.model.data, indent=4))
        
        # Update font JSON editor
        self.font_json_text.delete(1.0, "end")
        # Use compact format for font.json (no spaces)
        font_json_str = json.dumps(self.model.font_data, ensure_ascii=False, separators=(',', ':'))
        self.font_json_text.insert(1.0, font_json_str)

    def parse_time(self):
        try:
            hh = int(self.hour_var.get())
            mm = int(self.minute_var.get())
            ss = int(self.second_var.get())
            hh = max(0, min(23, hh))
            mm = max(0, min(59, mm))
            ss = max(0, min(59, ss))
            return datetime.time(hour=hh, minute=mm, second=ss)
        except:
            return datetime.time(10,8,36)

    def update_preview(self):
        when = self.parse_time()
        multi = {}
        img = self.renderer.render(when, multimeter_values=multi)
        self._show_image(img)

    def _show_image(self, img):
        self._last_img = ImageTk.PhotoImage(img)
        self.canvas.create_image(0,0, image=self._last_img, anchor="nw")

    def on_load_json(self):
        messagebox.showinfo("Coming Soon!", f"This feature is coming soon!")

    def on_save_json(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")], title="Save JSON")
        if not path: return
        try:
            self.model.save_json(path)
            messagebox.showinfo("Saved", f"Saved to {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_save_preview(self):
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG","*.png")], title="Save preview.png")
        if not path: return
        when = self.parse_time()
        multi = {}
        img = self.renderer.render(when, multimeter_values=multi)

        # Save preview at 272x324 resolution
        preview_width = 272
        preview_height = 324
    
        # Resize the rendered image (320x385) to 272x324
        preview_img = img.resize((preview_width, preview_height), Image.Resampling.LANCZOS)

        # Save the preview image
        preview_img.save(path)
        messagebox.showinfo("Saved", f"Preview saved to {path}")

    def on_add_bg(self):
        path = filedialog.askopenfilename(title="Choose Background", filetypes=[("Images","*.png")])
        if not path: return
        # Copy to working dir with its basename for clean packaging
        dst = os.path.basename(path)
        if path != dst:
            try:
                shutil.copy(path, dst)
            except:
                pass
        self.model.data["bkground"] = os.path.basename(dst)
        self.refresh_tree()
        self.update_preview()

    def on_unknown(self):
        messagebox.showinfo("How?!?", f"There will be ring and progressbar widgets on 1.?.?")

    def _ask_for_hand(self, label, key_centerx, key_centery, key_anchorx, key_anchory, key_image, item_idx=None):
        path = filedialog.askopenfilename(title=f"Choose {label} image", filetypes=[("Images","*.png")])
        if not path: return
        dst = os.path.basename(path)
        if path != dst:
            try:
                shutil.copy(path, dst)
            except:
                pass
        # Ensure there is a watch/time item
        item = None
        for it in self.model.data.get("item", []):
            if it.get("widget")=="watch" and it.get("type")=="time":
                item = it
                break
        if not item:
            item = {"widget":"watch","type":"time","x":0,"y":0,"w":CANVAS_W,"h":CANVAS_H,"fgcolor":"0xFFFFFFFF"}
            self.model.data["item"].append(item)

        item[key_image] = os.path.basename(dst)

        # popup to set center and anchor
        top = Toplevel(self.root)
        top.title(f"{label} Center & Anchor")

        # Default anchors for IDW20 (center of 320x385 = 160, 193)
        vars = { 
            "cx": IntVar(value= int(self._auto_center(dst)[0])),
            "cy": IntVar(value= int(self._auto_center(dst)[1])),
            "ax": IntVar(value= 160),  # Updated for 320 width
            "ay": IntVar(value= 193),  # Updated for 385 height
        }

        def save_and_close():
            item[key_centerx] = vars["cx"].get()
            item[key_centery] = vars["cy"].get()
            item[key_anchorx] = vars["ax"].get()
            item[key_anchory] = vars["ay"].get()
            top.destroy()
            self.refresh_tree()
            self.update_preview()

        for row,(lab,k) in enumerate([("center x","cx"),("center y","cy"),("anchor x","ax"),("anchor y","ay")]):
            Label(top, text=lab).grid(row=row, column=0, padx=4, pady=4, sticky="e")
            Entry(top, textvariable=vars[k], width=8).grid(row=row, column=1, padx=4, pady=4, sticky="w")
        Button(top, text="OK", command=save_and_close).grid(row=10, column=0, sticky="sw", padx=8, pady=8)

    def _auto_center(self, path):
        try:
            from PIL import Image
            img = Image.open(path)
            return (img.size[0]//2, img.size[1]//2)
        except:
            return (0,0)

    def on_add_hands(self):
        # Offers three prompts sequentially
        self._ask_for_hand("Hour Hand", "hourcenterx","hourcentery","houranchorx","houranchory","hour")
        self._ask_for_hand("Minute Hand", "mincenterx","mincentery","minanchorx","minanchory","minute")
        self._ask_for_hand("Second Hand", "seccenterx","seccentery","secanchorx","secanchory","second")

    def on_load_font_json(self):
        path = filedialog.askopenfilename(title="Load font.json", filetypes=[("JSON","*.json")], defaultextension=".json")
        if not path: return
        try:
            self.model.load_font_json(path)
            self.refresh_tree()
            messagebox.showinfo("Loaded", f"font.json loaded from {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_save_font_json(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")], title="Save font.json")
        if not path: return
        try:
            self.model.save_font_json(path)
            messagebox.showinfo("Saved", f"font.json saved to {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_apply_font_json(self):
        try:
            new_font_data = json.loads(self.font_json_text.get(1.0, "end"))
            self.model.font_data = new_font_data
            self.refresh_tree()
            messagebox.showinfo("Success", "font.json applied successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Invalid font.json: {e}")
    
    def on_add_widget(self):
        widget_type = self.widget_type.get()

        # Defaults for widget types - updated for 320x385 resolution
        defaults = {
            "time": {"widget": "custom", "type": "time", "x": 24, "y": 261, "w": 173, "h": 51, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g13", "fontnum": 11},
            "date": {"widget": "custom", "type": "date", "x": 79, "y": 333, "w": 84, "h": 24, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "style": 1, "font": "g14", "fontnum": 11},
            "week": {"widget": "custom", "type": "week", "x": 181, "y": 333, "w": 59, "h": 24, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "style": 0, "font": "week", "fontnum": 7},
            "day": {"widget": "custom", "type": "day", "x": 135, "y": 291, "w": 51, "h": 32, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g15", "fontnum": 10},
            "second": {"widget": "custom", "type": "second", "x": 219, "y": 261, "w": 77, "h": 51, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g24", "fontnum": 10},
            "hour": {"widget": "custom", "type": "hour", "x": 16, "y": 46, "w": 133, "h": 104, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g16", "fontnum": 10},
            "min": {"widget": "custom", "type": "min", "x": 16, "y": 150, "w": 136, "h": 104, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g17", "fontnum": 10},
            "year": {"widget": "custom", "type": "year", "x": 99, "y": 265, "w": 64, "h": 21, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g18", "fontnum": 11},
            "heartrate": {"widget": "custom", "type": "heartrate", "x": 203, "y": 250, "w": 40, "h": 16, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g19", "fontnum": 11},
            "calorie": {"widget": "custom", "type": "calorie", "x": 48, "y": 337, "w": 67, "h": 28, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g20", "fontnum": 10},
            "distance": {"widget": "custom", "type": "distance", "x": 72, "y": 202, "w": 37, "h": 16, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "metricinch": 1, "font": "distance", "fontnum": 11},
            "step": {"widget": "custom", "type": "step", "x": 48, "y": 269, "w": 80, "h": 28, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g21", "fontnum": 10},
            "battery": {"widget": "custom", "type": "battery", "x": 203, "y": 292, "w": 59, "h": 16, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "g22", "fontnum": 11},
            "weather": {"widget": "custom", "type": "weather", "x": 200, "y": 85, "w": 64, "h": 16, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "center", "style": 2, "font": "g23", "fontnum": 13},
            "apm": {"widget": "custom", "type": "apm", "x": 101, "y": 296, "w": 37, "h": 16, "fgcolor": "0xFFFFFFFF", "fgrender": "0xFFFFFFFF", "align": "left", "font": "apm", "fontnum": 2},
        }
        
        if widget_type in defaults:
            widget = defaults[widget_type].copy()
        else:
            widget = {
                "widget": "custom",
                "type": widget_type,
                "x": 0, "y": 0, "w": 50, "h": 20,
                "fgcolor": "0xFFFFFFFF",
                "fgrender": "0x0",
                "align": "left",
                "font": widget_type,
                "fontnum": 10
            }
        
        # Get font name from widget
        font_name = widget.get("font", widget_type)
        
        # Add font to font.json if it doesn't exist
        if font_name and font_name not in [item.get("name", "") for item in self.model.font_data.get("item", [])]:
            self.model.font_data["item"].append({"name": font_name, "bpp": 16, "format": "png"})
        
        # Add widget to model
        self.model.data.setdefault("item", []).append(widget)
        self.refresh_tree()
        self.update_preview()

        # Ask for FOLDER instead of individual PNG files
        folder_path = filedialog.askdirectory(
            title=f"Select PNG Folder for {widget_type} widget (font: {font_name})",
            mustexist=True
        )
        
        if folder_path:
            # Create destination folder structure
            # widgets/[widget_type]/[font_name]/
            dest_folder = os.path.join("widgets", widget_type, font_name)
            if not os.path.exists(dest_folder):
                os.makedirs(dest_folder, exist_ok=True)
            
            # Copy all PNG files from selected folder
            copied_count = 0
            for filename in os.listdir(folder_path):
                if filename.lower().endswith('.png'):
                    src_file = os.path.join(folder_path, filename)
                    dst_file = os.path.join(dest_folder, filename)
                    try:
                        shutil.copy2(src_file, dst_file)
                        copied_count += 1
                        print(f"Copied: {filename}")
                    except Exception as e:
                        print(f"Failed to copy {filename}: {e}")
            
            # Also copy to widgets/[widget_type]/ for backward compatibility
            simple_dest_folder = os.path.join("widgets", widget_type)
            if not os.path.exists(simple_dest_folder):
                os.makedirs(simple_dest_folder, exist_ok=True)
            
            for filename in os.listdir(folder_path):
                if filename.lower().endswith('.png'):
                    src_file = os.path.join(folder_path, filename)
                    dst_file = os.path.join(simple_dest_folder, filename)
                    try:
                        shutil.copy2(src_file, dst_file)
                    except Exception as e:
                        pass  # Ignore errors for second copy
            
            if copied_count > 0:
                messagebox.showinfo("Widget PNGs Added", 
                    f"Copied {copied_count} PNG files from folder:\n"
                    f"{folder_path}\n"
                    f"to: {dest_folder}")
                self.update_preview()
            else:
                messagebox.showwarning("No PNGs Found", 
                    f"No PNG files found in selected folder:\n{folder_path}")
        else:
            # User cancelled folder selection
            # Create empty folder structure for later
            dest_folder = os.path.join("widgets", widget_type, font_name)
            if not os.path.exists(dest_folder):
                os.makedirs(dest_folder, exist_ok=True)
            
            messagebox.showwarning("No Folder Selected", 
                f"No folder selected for {widget_type}.\n"
                f"You can add PNGs later in: {dest_folder}")

    def on_remove_widget(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a widget to remove.")
            return
        
        item_id = selected[0]
        item_text = self.tree.item(item_id, "text")
        
        # Find the parent item to determine if this is a widget
        parent_id = self.tree.parent(item_id)
        if parent_id and self.tree.item(parent_id, "text") == "item:":
            # This is a widget item
            if ":" in item_text:
                idx = int(item_text.split(":")[0])
                if 0 <= idx < len(self.model.data["item"]):
                    del self.model.data["item"][idx]
                    self.refresh_tree()
                    self.update_preview()
                    return
        
        messagebox.showwarning("Invalid Selection", "Please select a widget to remove.")

    def on_apply_json(self):
        try:
            new_data = json.loads(self.json_text.get(1.0, "end"))
            self.model.data = new_data
            self.refresh_tree()
            self.update_preview()
            messagebox.showinfo("Success", "iwf.json applied successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Invalid iwf.json: {e}")

    def on_apply_custom_time(self):
        """Apply custom time to preview"""
        try:
            # Validate inputs
            hh = int(self.hour_var.get())
            mm = int(self.minute_var.get())
            ss = int(self.second_var.get())
            
            if hh < 0 or hh > 23:
                messagebox.showerror("Error", "Hour must be between 0 and 23")
                return
            if mm < 0 or mm > 59:
                messagebox.showerror("Error", "Minute must be between 0 and 59")
                return
            if ss < 0 or ss > 59:
                messagebox.showerror("Error", "Second must be between 0 and 59")
                return
            
            # Update preview with custom time
            self.update_preview()
            messagebox.showinfo("Success", f"Time set to {hh:02d}:{mm:02d}:{ss:02d}")
            
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers for time")

    def on_update_widget_preview(self):
        """Update widget preview value"""
        widget_type = self.preview_widget_type.get()
        value = self.preview_widget_value.get()
        
        if not value:
            messagebox.showerror("Error", "Please enter a value")
            return
        
        # Update the renderer with new widget value
        if self.renderer.update_widget_value(widget_type, value):
            self.update_preview()
            messagebox.showinfo("Success", f"{widget_type} preview updated to: {value}")
        else:
            messagebox.showerror("Error", f"Invalid widget type: {widget_type}")

if __name__ == "__main__":
    root = Tk()
    app = App(root)
    app.refresh_tree()
    app.update_preview()
    root.mainloop()
