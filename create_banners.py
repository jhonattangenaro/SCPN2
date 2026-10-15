# create_banners.py
from PIL import Image, ImageDraw, ImageFont
import os

os.makedirs('static', exist_ok=True)

def create_banner(filename, text_lines, bg_color='#0B3B6E'):  # Azul principal
    img = Image.new('RGB', (1200, 300), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("arial.ttf", 40)
        font_small = ImageFont.truetype("arial.ttf", 30)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        except:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()
    
    y_position = 50
    for i, line in enumerate(text_lines):
        if i == 0:
            draw.text((100, y_position), line.strip(), fill='white', font=font)
            y_position += 60
        else:
            draw.text((120, y_position), line.strip(), fill='#F5A623' if 'AQUÍ' in line else 'white', font=font_small)
            y_position += 45
    
    img.save(f'static/{filename}')
    print(f"✅ Creado: static/{filename}")

banner_text = [
    "CONSULTA",
    "POPULAR NACIONAL",
    "2026",
    "¡AQUÍ MANDA EL PUEBLO!",
    "",
    "CENTROS Y",
    "MESAS ELECTORALES",
    "PARA LA CONSULTA POPULAR NACIONAL DEL 8M"
]

create_banner('banner_header.jpg', banner_text, bg_color='#0B3B6E')
create_banner('banner_footer.jpg', banner_text, bg_color='#F5A623')  # Amarillo
print("¡Banners creados exitosamente!")