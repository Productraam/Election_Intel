"""Quick test: WinOCR output through parser."""
import asyncio, fitz, time
from PIL import Image
import io as _io
import winocr

PDF_PATH = r'C:\Users\Dhuttarge\Downloads\2024-FC-EROLLGEN-S10-46-FinalRoll-Revision2-ENG-12-WI.pdf'

async def main():
    doc = fitz.open(PDF_PATH)
    # Page 3 is a dense voter page
    page = doc[2]
    pix = page.get_pixmap(dpi=150)
    img = Image.open(_io.BytesIO(pix.tobytes('png')))
    
    start = time.time()
    result = await winocr.recognize_pil(img, lang='en')
    elapsed = time.time() - start
    
    text = result.text
    print(f"Page 3 OCR ({elapsed:.1f}s): {len(text)} chars")
    print("=" * 60)
    print(text[:2000])
    print("=" * 60)
    
    # Now test through parser
    from voter_parser import VoterListParser
    parser = VoterListParser()
    
    # Debug: show line count
    lines = text.split('\n')
    print(f"\nLine count: {len(lines)}")
    for i, line in enumerate(lines[:10]):
        print(f"  Line {i}: {line[:100]}...")
    
    result = parser._parse_eci_roll_format(text)
    print(f"\nParser found: {len(parser.voters)} voters")
    for v in parser.voters[:10]:
        print(f"  #{v.get('sr_no','?'):>2} | {v.get('name',''):25} | Age:{v.get('age','')} | {v.get('gender','')} | House:{v.get('house_no','')}")

asyncio.run(main())
