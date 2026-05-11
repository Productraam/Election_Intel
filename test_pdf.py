"""Quick test of parsing against known OCR output from page 3"""
from voter_parser import VoterListParser
import re

# This is the actual OCR output from page 3 of the ECI voter list
ocr_text = """Assembly Constituency No and Name 46-ALAND Section No and Name 1-KhajuriH.No. 1/1 to 1153 NQT6237796 Nama nasarean galid Nama sangeata Husbands Narre: mubarak nusband Husbands Nare: Hyamanna House Numoor 1/153/3 Photo Houso Number NA Age 28 Gender Female Age 36 Gender Female Available
Part No. 12
NQT5583489
NQT6587224
Name SAMEER Nimbalkar Fatners Narie: RIZWANA NIBALKAR House Numbor khaluri Age 20 GCender Male
Pnoto
Photo
Available
Availablc
NQT6390561
NQT6414189
NQT6518500
Namo MALLIKARJUN Fathers Name: SHNANAND TALAWAR House Number KhAURI Age 21 Gendar Male
Namo Muksana Fathers Name: Maheboob House Number Khajuri Age 20 Gerder Female
Namc GURAPPA Fathers Name: CHANDRASHA Housa Number KHAjuRI Aga 24 Gender Male
Photo
Photo
Photo
Available
Avallable
Avallable
NCT6518609
NCT6533525
N0T6533533
Nama SAIBANNA Falhers Name: CHANDRASHA HADAPAD House Numper KHAJURI Age 26 Gencer Male
Name SUVARNA Husbands Name: MANJUNATH House Number KHAJURI Age 20 Gender Female
Name MANJUNATHRAANThrI Falners Namie: RAJENDRA House Number KHAJURI Age 25 Gender Male
Photo
Pnoto
Photo
Avallablo
Available
Available
10 Namne Anupamia Fathers Name; Rajshekhar Kumbar House Number Khajuri Age 19 Gender Famale
Na16544878
NaT6578306
12 Name Sharnamnma Husoands Namo; Shamarao hebale House Number khajuri Aga : 57 Gander Female
NQ16587372
Narne SAVITRI Husbands Name; SANTOSH DURGE House Number KHAJURI Aga 36 Gerder Female
Photo
Photo
Photo
Available
Available
Available
13
NQT6589378
74
N0T6440622
15
NQT6587349
Name Ashvini Husbands Name: Umesh Hadapad House Numnbur Khajuri Ago ; 31 Gendor Fomalo
Name IRANNA Fathers Name: NAGANNA MASHALE Hause Numnber VENKATESHWAR Ago 40 Gondor Male
Name Priti Huspands Name: Ramesh Hllapale Huusa Number Venkaleshwar Nagar Age 20 Gonder Femalo
Photo
Photo
Photo
Avallable
Avallable
Avallable
16
NQT6454565
N016454755
18
NQ16218820
Nama Sunanda Husbands Namo: Vijayslng Rajput House Number 00 Age 57 Gender Female
Narna AISHWARYA Fathers Namo: CI IANADASAPPA NAGA House Number 0o Age 21 Gender Female
Narne Namnadal Husoand: Namo: Tulaslram House Number Age 72 Gender Female
Photo
Photo
Photo
Available
Available
Available
19
NQT6198063
20 Name Chand Sab Fathers Name: Mehabaab Sab Hause Nurnber 11 Age 74 Gender Male
NoT5888508
21
Not5888516
Name VISHAL Fathers Name: SHRIPAL House Numiber Age 28 Genaer Male
Name Mehboob Bee Huspands Name: Chand Sab Hausa Number V1 Age 64 Gender Fema
"""

parser = VoterListParser()

# Test the new parsing methods directly
parser._extract_metadata(ocr_text)
print("Metadata:", parser.metadata)

# Run the ECI roll parser
parser._parse_eci_roll_format(ocr_text)
print(f"\nStrict parser found: {len(parser.voters)} voters")

if len(parser.voters) < 5:
    print("Trying lenient parser...")
    parser.voters.clear()
    parser._parse_eci_roll_lenient(ocr_text)
    print(f"Lenient parser found: {len(parser.voters)} voters")

if parser.voters:
    parser._post_process()
    print("\n=== Parsed Voters ===")
    for v in parser.voters:
        print(f"  #{v['sr_no']:>3} | {v['name'][:25]:25} | Rel: {v['father_name'][:20]:20} | Age:{str(v['age']):>3} | {str(v['gender']):>6} | House:{v['house_no'][:15]} | {v['voter_id']}")
else:
    print("\nNo voters parsed! Dumping NQT matches...")
    for m in re.finditer(r'N[QqOo0C][Tt]\d{5,10}', ocr_text, re.IGNORECASE):
        print(f"  Found NQT: {m.group()} at pos {m.start()}")

# Show lines we MISSED
print("\n=== MISSED lines with Name+Age ===")
parsed_names = {v['name'][:15].lower() for v in parser.voters}
for line in ocr_text.split('\n'):
    if re.search(r'Nam', line, re.IGNORECASE) and re.search(r'Ag', line, re.IGNORECASE):
        # Check if any parsed voter name appears in this line
        found = any(n in line.lower() for n in parsed_names if n)
        if not found and len(line) > 20:
            print(f"  MISS: {line[:120]}")

