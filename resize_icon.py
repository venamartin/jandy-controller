from PIL import Image

def process_icon(input_path, output_path, size=192):
    try:
        # Open and ensure it has an alpha channel
        img = Image.open(input_path).convert("RGBA")
        
        # 1. Find the bounding box of the visible (non-transparent) pixels
        # We split the channels and get the bounding box of the Alpha channel
        alpha = img.split()[-1]
        bbox = alpha.getbbox()
        
        if bbox:
            img = img.crop(bbox)
        
        # 2. Make it a perfect square by padding (not cutting!)
        w, h = img.size
        max_dim = max(w, h)
        
        # Optional: Add a tiny bit of padding (e.g. 5%) so it doesn't touch the absolute edge
        padding = int(max_dim * 0.05)
        canvas_size = max_dim + (padding * 2)
        
        # Create a new transparent square canvas
        square_img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        
        # Paste the cropped image perfectly in the center of the square canvas
        paste_x = (canvas_size - w) // 2
        paste_y = (canvas_size - h) // 2
        square_img.paste(img, (paste_x, paste_y))
        
        # 3. Finally, resize the square canvas down to the target size
        final_img = square_img.resize((size, size), Image.Resampling.LANCZOS)
        
        final_img.save(output_path, format="PNG")
        print(f"Successfully trimmed, squared, and resized to {output_path} ({size}x{size})")
        
    except Exception as e:
        print(f"Error processing image: {e}")

if __name__ == "__main__":
    process_icon("static/pool.png", "static/icon.png", 192)
