"""Benchmark different OCR engines on the voter PDF."""
import time, fitz, asyncio
from PIL import Image
import io as _io
import numpy as np

PDF_PATH = r'C:\Users\Dhuttarge\Downloads\2024-FC-EROLLGEN-S10-46-FinalRoll-Revision2-ENG-12-WI.pdf'

def get_page_images(doc, pages=3, dpi=150):
    """Pre-render pages to images."""
    images = []
    for i in range(min(pages, len(doc))):
        page = doc[i]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(_io.BytesIO(pix.tobytes('png')))
        images.append(img)
    return images

async def bench_winocr(images):
    """Benchmark Windows native OCR."""
    import winocr
    print("\n=== WinOCR (Windows native) ===")
    start = time.time()
    for i, img in enumerate(images):
        result = await winocr.recognize_pil(img, lang='en')
        text = result.text
        print(f"  Page {i+1}: {len(text)} chars ({time.time()-start:.1f}s)")
    elapsed = time.time() - start
    print(f"  => {elapsed:.1f}s for {len(images)} pages = {elapsed/len(images):.1f}s/page")
    print(f"  => 50 pages estimate: {elapsed/len(images)*50:.0f}s")
    return elapsed

def bench_rapidocr(images):
    """Benchmark RapidOCR."""
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    print("\n=== RapidOCR (ONNX) ===")
    start = time.time()
    for i, img in enumerate(images):
        img_np = np.array(img)
        result, _ = engine(img_np)
        text = "\n".join([line[1] for line in result]) if result else ""
        print(f"  Page {i+1}: {len(text)} chars ({time.time()-start:.1f}s)")
    elapsed = time.time() - start
    print(f"  => {elapsed:.1f}s for {len(images)} pages = {elapsed/len(images):.1f}s/page")
    print(f"  => 50 pages estimate: {elapsed/len(images)*50:.0f}s")
    return elapsed

async def main():
    doc = fitz.open(PDF_PATH)
    print(f"PDF: {len(doc)} pages")
    
    # Test with page 3 (dense voter page) at lower DPI
    print("\nRendering 3 pages at DPI=150...")
    images = get_page_images(doc, pages=3, dpi=150)
    print(f"  Image size: {images[0].size}")
    
    # WinOCR
    await bench_winocr(images)
    
    # RapidOCR at DPI=100 (fewer pixels)
    print("\nRendering 3 pages at DPI=100...")
    images_low = get_page_images(doc, pages=3, dpi=100)
    print(f"  Image size: {images_low[0].size}")
    bench_rapidocr(images_low)

if __name__ == '__main__':
    asyncio.run(main())
