"""Full 50-page speed test with WinOCR through the parser."""
import asyncio, fitz, time, sys
sys.path.insert(0, '.')
from voter_parser import VoterListParser

PDF_PATH = r'C:\Users\Dhuttarge\Downloads\2024-FC-EROLLGEN-S10-46-FinalRoll-Revision2-ENG-12-WI.pdf'

def main():
    start = time.time()
    parser = VoterListParser()
    
    with open(PDF_PATH, 'rb') as f:
        data = parser.parse_pdf_stream(f)
    
    elapsed = time.time() - start
    voters = parser.voters
    print(f"\n{'='*60}")
    print(f"RESULT: {len(voters)} voters from 50 pages in {elapsed:.1f}s")
    print(f"Speed: {elapsed/50:.1f}s/page")
    print(f"{'='*60}")
    
    # Show sample voters
    for v in voters[:5]:
        print(f"  {v.get('name',''):25} | Age:{v.get('age',''):>3} | {v.get('gender',''):6} | House:{v.get('house_no','')}")

if __name__ == '__main__':
    main()
