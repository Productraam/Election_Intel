"""
Election Intelligence - Voter List Parser
Parses ECI voter list drafts (PDF, CSV, TXT) and enriches data with:
- Unique NQT ID mapping
- Age & Gender extraction
- Family linkage (household grouping)
- Caste/Community inference from surname
"""

import re
import csv
import io
import hashlib
from collections import defaultdict
from datetime import datetime

# Surname → Community mapping (expandable)
SURNAME_COMMUNITY = {
    'sharma': 'Brahmin', 'shukla': 'Brahmin', 'tiwari': 'Brahmin', 'pandey': 'Brahmin',
    'mishra': 'Brahmin', 'dubey': 'Brahmin', 'joshi': 'Brahmin', 'pathak': 'Brahmin',
    'dwivedi': 'Brahmin', 'tripathi': 'Brahmin', 'upadhyay': 'Brahmin', 'kaushik': 'Brahmin',
    'ojha': 'Brahmin', 'bajpai': 'Brahmin', 'chaturvedi': 'Brahmin',
    'yadav': 'OBC-Yadav', 'mandal': 'OBC', 'kurmi': 'OBC', 'kushwaha': 'OBC',
    'patel': 'OBC-Patel', 'lodhi': 'OBC', 'nishad': 'OBC', 'maurya': 'OBC',
    'gupta': 'Vaishya', 'agarwal': 'Vaishya', 'aggarwal': 'Vaishya',
    'jain': 'Jain', 'goel': 'Vaishya', 'bansal': 'Vaishya', 'mittal': 'Vaishya',
    'singh': 'Rajput/Sikh', 'chauhan': 'Rajput', 'rathore': 'Rajput', 'thakur': 'Rajput',
    'rawat': 'Rajput', 'tomar': 'Rajput', 'panwar': 'Rajput',
    'pal': 'OBC', 'verma': 'OBC', 'saxena': 'Kayastha', 'srivastava': 'Kayastha',
    'nigam': 'Kayastha', 'mathur': 'Kayastha',
    'kumar': 'Mixed', 'prasad': 'Mixed', 'ram': 'SC', 'paswan': 'SC-LJP',
    'jatav': 'SC-BSP', 'valmiki': 'SC', 'dhobi': 'SC', 'chamar': 'SC',
    'khan': 'Muslim', 'ahmed': 'Muslim', 'sheikh': 'Muslim', 'ansari': 'Muslim-OBC',
    'siddiqui': 'Muslim', 'qureshi': 'Muslim',
    'malik': 'Jat/Muslim', 'jat': 'Jat', 'dalal': 'Jat', 'hooda': 'Jat',
    'reddy': 'Reddy', 'naidu': 'Kamma', 'nair': 'Nair', 'menon': 'Nair',
    'pillai': 'Ezhava', 'iyer': 'Tamil-Brahmin', 'iyengar': 'Tamil-Brahmin',
    'devi': 'Mixed', 'kumari': 'Mixed', 'bai': 'Mixed',
    'meena': 'ST', 'bhil': 'ST', 'gond': 'ST', 'oraon': 'ST', 'munda': 'ST',
}


class VoterListParser:
    """Parse ECI voter list drafts and enrich with NQT, family, community data"""

    def __init__(self):
        self.voters = []
        self._page_texts = []
        self.metadata = {
            'state': None, 'district': None, 'assembly': None,
            'ac_no': None, 'part_no': None, 'polling_station': None,
            'total_voters': 0, 'male_voters': 0, 'female_voters': 0,
            'parse_date': datetime.now().isoformat(), 'source_format': None,
            # Page 1 — Constituency & Roll
            'roll_year': None,
            'reservation_status_ac': None,
            'parliamentary_constituency': None,
            'pc_no': None,
            'reservation_status_pc': None,
            # Page 1 — Revision
            'qualifying_date': None,
            'revision_type': None,
            'date_of_updation': None,
            'roll_identification': None,
            # Page 1 — Section & Polling
            'section_no_name': None,
            'polling_station_address': None,
            'polling_station_type': None,
            'auxiliary_polling_stations': None,
            # Page 1 — Location
            'main_village_town': None,
            'ward': None,
            'post_office': None,
            'police_station': None,
            'tehsil': None,
            'pincode': None,
            # Page 1 — Net Electors
            'net_electors_male': None,
            'net_electors_female': None,
            'net_electors_third_gender': None,
            'net_electors_total': None,
            'starting_serial_no': None,
            'ending_serial_no': None,
            'total_pages_in_roll': None,
        }

    # ─── Public Parse Methods ───────────────────────────────────────

    def parse_pdf_stream(self, stream, max_pages=None):
        """Parse PDF voter list from file stream.
        Handles both text-based and image-based (scanned) ECI PDFs.
        Uses OCR (EasyOCR) for image-based PDFs.
        max_pages: limit how many pages to OCR (None = all).
        """
        import fitz  # PyMuPDF

        doc = fitz.open(stream=stream.read(), filetype="pdf")
        total_pages = len(doc)

        # Check if PDF is image-based (first non-empty page)
        is_image_pdf = True
        for i in range(min(5, total_pages)):
            if len(doc[i].get_text().strip()) > 50:
                is_image_pdf = False
                break

        full_text = ""

        if is_image_pdf:
            # OCR path: render pages to images, run EasyOCR
            full_text = self._ocr_pdf(doc, max_pages=max_pages)
            # OCR page 1 at higher DPI for cover-page metadata (numbers get lost at 150 DPI)
            page1_text = self._ocr_page1_hq(doc)
        else:
            # Text-based PDF: extract text directly
            self._page_texts = []
            for page in doc:
                page_text = page.get_text()
                self._page_texts.append(page_text)
                full_text += page_text + "\n"
            page1_text = doc[0].get_text() if total_pages > 0 else ""

        doc.close()

        self._extract_metadata(full_text)
        # Page 1 at higher DPI fills in any missing values (numbers get lost at 150 DPI)
        if page1_text:
            self._extract_page1_details(page1_text, fill_only=True)
        self.metadata['source_format'] = 'pdf'
        self.metadata['total_pages'] = total_pages
        self.metadata['ocr_used'] = is_image_pdf

        # Parse the ECI electoral roll format
        self._parse_eci_roll_format(full_text)

        # Fallback strategies
        if not self.voters:
            self._parse_eci_box_text(full_text)
        if not self.voters:
            self._parse_eci_text(full_text)

        self._post_process()
        return self.voters

    def _ocr_pdf(self, doc, dpi=150, max_pages=None):
        """OCR all pages. Uses Windows native OCR (winocr) when available
        (~0.6s/page on Windows); falls back to Tesseract (pytesseract) on
        Linux/macOS or when winocr is unavailable. Returns the joined text
        and stores per-page texts in self._page_texts."""
        from PIL import Image
        import io as _io
        import time

        pages_to_process = min(max_pages or len(doc), len(doc))
        start_time = time.time()

        # Detect OCR backend
        try:
            import asyncio
            import winocr  # noqa: F401
            backend = 'winocr'
        except Exception:
            try:
                import pytesseract  # noqa: F401
                backend = 'tesseract'
            except Exception:
                raise RuntimeError(
                    "No OCR backend available. Install 'winocr' (Windows) or "
                    "'pytesseract' + Tesseract binary (Linux/macOS)."
                )

        all_text = []
        if backend == 'winocr':
            import asyncio
            import winocr

            async def ocr_all():
                out = []
                for i in range(pages_to_process):
                    page = doc[i]
                    pix = page.get_pixmap(dpi=dpi)
                    img = Image.open(_io.BytesIO(pix.tobytes('png')))
                    result = await winocr.recognize_pil(img, lang='en')
                    out.append(result.text)
                    print(f"  OCR page {i+1}/{pages_to_process} ({time.time()-start_time:.1f}s)", flush=True)
                return out

            all_text = asyncio.run(ocr_all())
        else:
            import pytesseract
            for i in range(pages_to_process):
                page = doc[i]
                pix = page.get_pixmap(dpi=dpi)
                img = Image.open(_io.BytesIO(pix.tobytes('png')))
                txt = pytesseract.image_to_string(img, lang='eng')
                all_text.append(txt)
                print(f"  OCR page {i+1}/{pages_to_process} ({time.time()-start_time:.1f}s)", flush=True)

        total_time = time.time() - start_time
        print(f"  OCR complete ({backend}): {pages_to_process} pages in {total_time:.1f}s ({total_time/pages_to_process:.1f}s/page)", flush=True)
        self._page_texts = list(all_text)
        return "\n\n".join(all_text)

    def _ocr_page1_hq(self, doc, dpi=250):
        """OCR just page 1 at higher DPI for accurate cover-page metadata."""
        from PIL import Image
        import io as _io

        if len(doc) == 0:
            return ""
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(_io.BytesIO(pix.tobytes('png')))

        try:
            import asyncio
            import winocr

            async def _ocr():
                return await winocr.recognize_pil(img, lang='en')

            return asyncio.run(_ocr()).text
        except Exception:
            try:
                import pytesseract
                return pytesseract.image_to_string(img, lang='eng')
            except Exception:
                return ""

    def _parse_eci_roll_format(self, text):
        """Parse ECI electoral roll from OCR text.
        
        The OCR output has a specific pattern:
        - NQT IDs appear on separate lines (often grouped: 3 IDs then 3 voter lines)
        - Voter details on separate lines: Name <name> Father's Name: <rel> House Number <addr> Age <n> Gender <g>
        - OCR introduces heavy typos in keywords and names
        
        Strategy: extract all voter detail lines independently, extract all NQT IDs,
        then match them by position in text.
        """
        lines = text.split('\n')
        
        # Phase 1: Extract all NQT-like IDs with their positions
        nqt_pattern = re.compile(
            r'\b(N[QqOo0Ca][Tt1]\d{5,10}|JRD\d{5,10})\b',
            re.IGNORECASE
        )
        nqt_entries = []  # (line_index, nqt_id)
        for i, line in enumerate(lines):
            for m in nqt_pattern.finditer(line):
                nqt_id = m.group(1).strip()
                # Normalize OCR misreads: NCT->NQT, N0T->NQT, NaT->NQT, etc.
                nqt_id = re.sub(r'^N[^Q]T', 'NQT', nqt_id, flags=re.IGNORECASE).upper()
                nqt_entries.append((i, nqt_id))
        
        # Phase 2: Extract all voter detail lines
        # A voter detail line has Name + (Father/Husband) + Age + Gender
        # OCR produces many typos - use very broad patterns:
        name_kw = r'(?:Nam\w{0,5}|Narn\w{0,3}|Nare)'
        rel_kw = r'(?:Fat\w{0,6}|Fal\w{0,6}|Hus[bpo]\w{0,6}|Mot\w{0,6}|Guard\w{0,6})'
        rel_name_kw = r'(?:Nam\w{0,5}|Narn\w{0,3}|Nare|Namie)'
        house_kw = r'(?:H[oau]{1,2}[usa]\w?\s*(?:Num\w{0,6}|No\w{0,3})?)'
        age_kw = r'(?:Ag[aeo])'
        gender_kw = r'(?:G\w{1,5}r|Gender|Genaer|GCender)'
        gender_val = r'(Mal\w{0,4}|Fem\w{0,5}|Fom\w{0,4}|Fam\w{0,4})'
        
        voter_detail_pattern = re.compile(
            name_kw + r'\s*[;:\s]+(.+?)\s+'  # Name value
            + rel_kw + r'[\s:]*(?:' + rel_name_kw + r')?[;:\s]*(.+?)\s+'  # Relation value
            + house_kw + r'[;:\s]*(.+?)\s*'  # House value
            + age_kw + r'\s*[;:\s]*(\d{1,3})\s*'  # Age value
            + gender_kw + r'\s*[;:\s]*' + gender_val,  # Gender value
            re.IGNORECASE
        )
        
        voter_details = []  # (line_index, parsed_dict)
        for i, line in enumerate(lines):
            # Check for serial number prefix
            sr_match = re.match(r'^\s*(\d{1,4})\s+', line)
            sr_no = sr_match.group(1) if sr_match else None
            
            for m in voter_detail_pattern.finditer(line):
                name = m.group(1).strip()
                father = m.group(2).strip()
                house = m.group(3).strip()
                age_str = m.group(4)
                gender_raw = m.group(5)
                
                # Clean captured fields
                name = re.sub(r'\s*(Fat[nh]|Hus[bp]|Photo|Avail).*$', '', name, flags=re.IGNORECASE).strip()
                father = re.sub(r'\s*(Hou[sa]|Photo|Avail|Age).*$', '', father, flags=re.IGNORECASE).strip()
                house = re.sub(r'\s*(Ag[aeo]|Photo|Avail).*$', '', house, flags=re.IGNORECASE).strip()
                
                age = None
                try:
                    age = int(age_str)
                    if age < 18 or age > 120:
                        age = None
                except (ValueError, TypeError):
                    pass
                
                if name and len(name) >= 2:
                    # Skip header lines parsed as voters
                    if re.search(r'(Assembly|Constituency|Section|Part\s*No|ALAND|H\.No)', name, re.IGNORECASE):
                        continue
                    voter_details.append((i, {
                        'sr_no': sr_no or str(len(voter_details) + 1),
                        'name': re.sub(r'\s+', ' ', name)[:60],
                        'father_name': re.sub(r'\s+', ' ', father)[:60],
                        'age': age,
                        'gender': self._norm_gender(gender_raw),
                        'house_no': re.sub(r'\s+', ' ', house)[:60],
                        'address': '',
                        'part_no': self.metadata.get('part_no', ''),
                    }))
        
        # Phase 3: Match NQT IDs to voter details
        # NQT IDs typically appear just before the voter detail lines
        # Strategy: for each voter detail, find the closest preceding unused NQT ID
        used_nqts = set()
        for v_idx, (v_line, voter) in enumerate(voter_details):
            best_nqt = None
            best_dist = float('inf')
            for n_idx, (n_line, nqt_id) in enumerate(nqt_entries):
                if n_idx in used_nqts:
                    continue
                # NQT should be before or on same line as voter, within ~10 lines
                dist = v_line - n_line
                if 0 <= dist <= 10 and dist < best_dist:
                    best_dist = dist
                    best_nqt = n_idx
            
            if best_nqt is not None:
                voter['voter_id'] = nqt_entries[best_nqt][1]
                used_nqts.add(best_nqt)
            else:
                voter['voter_id'] = ''
            
            self.voters.append(voter)
        
        # Phase 4: If we found very few voters, some voter lines might have
        # different formats. Try line-by-line extraction as fallback.
        if len(self.voters) < 5:
            self._parse_eci_roll_fallback(text, nqt_entries)

    def _parse_eci_roll_fallback(self, text, nqt_entries):
        """Fallback: extract voters by splitting on Name keywords line by line"""
        existing_ids = {v.get('voter_id', '') for v in self.voters}
        
        # Find all lines that have Name + Age pattern but may have OCR variations
        # we didn't catch with the strict regex
        for line in text.split('\n'):
            line = line.strip()
            if len(line) < 20:
                continue
            
            # Must have some form of Name and Age on the same line
            if not re.search(r'Nam', line, re.IGNORECASE):
                continue
            if not re.search(r'Ag[aeo]', line, re.IGNORECASE):
                continue
            
            # Extract name: everything after Name keyword until next keyword
            name_m = re.search(r'Nam\w*\s*[;:\s]+([A-Za-z\s.]+?)(?:\s+(?:Fat|Hus|Mot|Gua|Hou|Ag|Ph))', line, re.IGNORECASE)
            if not name_m:
                continue
            name = name_m.group(1).strip()
            if not name or len(name) < 2:
                continue
            
            # Extract relation
            rel_m = re.search(r'(?:Fat\w+|Hus\w+|Mot\w+)\s*(?:Nam\w*)?[;:\s]+([A-Za-z\s.]+?)(?:\s+(?:Hou|Ag|Ph))', line, re.IGNORECASE)
            father = rel_m.group(1).strip() if rel_m else ''
            
            # Extract house
            house_m = re.search(r'Hou\w*\s*(?:Num\w*|No)?[;:\s]+([A-Za-z0-9\s/.,-]+?)(?:\s+Ag)', line, re.IGNORECASE)
            house = house_m.group(1).strip() if house_m else ''
            
            # Extract age
            age_m = re.search(r'Ag\w?\s*[;:\s]+(\d{1,3})', line, re.IGNORECASE)
            age = int(age_m.group(1)) if age_m else None
            if age and (age < 18 or age > 120):
                age = None
            
            # Extract gender
            gen_m = re.search(r'(?:G\w*nd\w*|[CG]ender)\s*[;:\s]*(Mal|Fem|Fom|Fam)\w*', line, re.IGNORECASE)
            gender = self._norm_gender(gen_m.group(1) if gen_m else '')
            
            # Serial number
            sr_m = re.match(r'^(\d{1,4})\s+', line)
            sr_no = sr_m.group(1) if sr_m else str(len(self.voters) + 1)
            
            self.voters.append({
                'sr_no': sr_no,
                'name': re.sub(r'\s+', ' ', name)[:60],
                'father_name': re.sub(r'\s+', ' ', father)[:60],
                'age': age,
                'gender': gender,
                'voter_id': '',
                'house_no': re.sub(r'\s+', ' ', house)[:60],
                'address': '',
                'part_no': self.metadata.get('part_no', ''),
            })

    def parse_csv_stream(self, stream, filename=''):
        """Parse CSV voter list from file stream"""
        content = stream.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        col_map = self._map_columns(reader.fieldnames or [])

        if not col_map.get('name'):
            raise ValueError("CSV must have a 'Name' column.")

        for i, row in enumerate(reader, 1):
            voter = self._extract_csv_row(row, col_map, i)
            if voter and voter['name']:
                self.voters.append(voter)

        self.metadata['source_format'] = 'csv'
        self._post_process()
        return self.voters

    def parse_text_stream(self, stream, filename=''):
        """Parse plain text voter list"""
        content = stream.read().decode('utf-8-sig')
        self._extract_metadata(content)
        self._parse_eci_text(content)
        self.metadata['source_format'] = 'txt'
        self._post_process()
        return self.voters

    # ─── Post Processing ────────────────────────────────────────────

    def _post_process(self):
        """Enrich all voters after parsing"""
        self._generate_nqt_ids()
        self._tag_page_numbers()
        self._infer_communities()
        self._link_families()
        self._add_voter_flags()
        self._update_metadata()

    def _tag_page_numbers(self):
        """Tag each voter with the printed PDF page number (the 'page N'
        marker shown at the bottom of each ECI roll page, e.g.
        'Total Pages 50 - page 3'). Falls back to the physical page index
        when the marker is missing.

        Uses self._page_texts (populated during PDF parsing) and counts how
        many voter records each physical page contains by matching the same
        NQT-id / EPIC pattern used in `_parse_eci_roll_format`. Voters keep
        their parse order, so we assign sequential page numbers by
        cumulative per-page counts. If page data is unavailable (CSV/TXT
        path), voters are left with page_no=0.
        """
        if not self._page_texts:
            for v in self.voters:
                v.setdefault('page_no', 0)
            return
        import re
        nqt_pat = re.compile(r'\b(N[QqOo0Ca][Tt1]\d{5,10}|JRD\d{5,10})\b', re.IGNORECASE)
        # Printed page marker, e.g. "Total Pages 50 - page 3" or "Page 4"
        # (case-insensitive, optional 'Total Pages NN -' prefix). Take the
        # LAST match on the page since the marker usually appears at the
        # bottom (we prefer it over any accidental "page" word earlier).
        page_marker_pat = re.compile(r'(?:total\s+pages?\s+\d+\s*[-\u2013\u2014]\s*)?page\s+(\d{1,4})\b', re.IGNORECASE)
        counts = []
        printed_pages = []
        for idx, ptxt in enumerate(self._page_texts):
            ptxt = ptxt or ''
            counts.append(len(nqt_pat.findall(ptxt)))
            matches = page_marker_pat.findall(ptxt)
            if matches:
                # Use the last (most likely the footer) marker
                try:
                    printed_pages.append(int(matches[-1]))
                except ValueError:
                    printed_pages.append(idx + 1)
            else:
                # Fall back to physical index if no marker found
                printed_pages.append(idx + 1)
        total_count = sum(counts)
        if total_count == 0 or len(self.voters) == 0:
            # Fallback: distribute uniformly across non-cover pages
            n_pages = max(1, len(self._page_texts) - 1)
            per_page = max(1, (len(self.voters) + n_pages - 1) // n_pages)
            for i, v in enumerate(self.voters):
                phys = min(len(self._page_texts) - 1, 1 + (i // per_page))
                v['page_no'] = printed_pages[phys] if phys < len(printed_pages) else (phys + 1)
            return
        # Scale per-page counts to actually-parsed voters in case OCR found
        # more NQT regex hits than the parser kept.
        scale = len(self.voters) / total_count
        allocations = [max(0, round(c * scale)) for c in counts]
        # Fix rounding drift
        drift = len(self.voters) - sum(allocations)
        if drift != 0:
            idx_max = max(range(len(allocations)), key=lambda k: counts[k])
            allocations[idx_max] += drift
        idx = 0
        for page_idx, n in enumerate(allocations):
            printed = printed_pages[page_idx]
            for _ in range(n):
                if idx < len(self.voters):
                    self.voters[idx]['page_no'] = printed  # printed page number
                    idx += 1
        # Any leftover voters (shouldn't happen) get the last printed page
        last_page = printed_pages[-1] if printed_pages else len(self._page_texts)
        while idx < len(self.voters):
            self.voters[idx]['page_no'] = last_page
            idx += 1

    def _update_metadata(self):
        self.metadata['total_voters'] = len(self.voters)
        self.metadata['male_voters'] = sum(1 for v in self.voters if v.get('gender') == 'Male')
        self.metadata['female_voters'] = sum(1 for v in self.voters if v.get('gender') == 'Female')

    def _generate_nqt_ids(self):
        """Generate stable NQT ID per voter.

        Strategy (in order of preference):
        1. If a real EPIC voter_id was extracted -> NQT-EPIC-{voter_id}
        2. Else hash on data that DOES NOT change across roll revisions:
           name + father + part_no  (deliberately NOT age or sr_no, since
           age increments yearly and sr_no shifts on every revision).
           NQT-{part}-{hash}
        This guarantees the same physical voter keeps the same NQT across
        successive ECI roll uploads for the same ward.
        """
        seen = {}
        for i, voter in enumerate(self.voters):
            part = str(voter.get('part_no', '0') or '0').strip()
            epic = (voter.get('voter_id') or '').strip().upper()
            if epic and len(epic) >= 6:
                nqt = f"NQT-EPIC-{epic}"
            else:
                name = (voter.get('name') or '').strip().lower()
                father = (voter.get('father_name') or '').strip().lower()
                raw = f"{name}|{father}|{part}"
                h = hashlib.sha256(raw.encode()).hexdigest()[:10].upper()
                nqt = f"NQT-{part.zfill(3)}-{h}"
            # On rare collisions (e.g. two voters with identical name+father+part
            # and no EPIC), suffix with sr_no to disambiguate.
            if nqt in seen:
                sr = str(voter.get('sr_no', i + 1)).strip()
                nqt = f"{nqt}-{sr}"
            seen[nqt] = True
            voter['nqt_id'] = nqt

    def _infer_communities(self):
        """Infer caste/community from surname"""
        for voter in self.voters:
            parts = voter['name'].strip().split()
            surname = parts[-1].lower() if parts else ''
            voter['surname'] = parts[-1] if parts else ''
            voter['community'] = SURNAME_COMMUNITY.get(surname, 'Unknown')

    def _link_families(self):
        """Group voters into families by father name + house + part"""
        family_map = defaultdict(list)
        for voter in self.voters:
            father = (voter.get('father_name') or '').strip().lower()
            house = (voter.get('house_no') or '').strip()
            part = voter.get('part_no', '')
            if father:
                key = f"{father}|{house}|{part}"
                family_map[key].append(voter['nqt_id'])

        assigned = {}
        for fid_num, (key, members) in enumerate(family_map.items(), 1):
            fid = f"FAM-{fid_num:06d}"
            for nqt_id in members:
                assigned[nqt_id] = (fid, len(members))

        for voter in self.voters:
            info = assigned.get(voter['nqt_id'])
            voter['family_id'] = info[0] if info else None
            voter['family_size'] = info[1] if info else 1

    def _add_voter_flags(self):
        """Add strategic flags to each voter"""
        for voter in self.voters:
            age = voter.get('age')
            voter['is_first_time'] = age is not None and 18 <= age <= 19
            voter['is_youth'] = age is not None and 18 <= age <= 25
            voter['is_senior'] = age is not None and age >= 60
            voter['is_very_old'] = age is not None and age >= 80
            voter['needs_transport'] = voter['is_very_old'] or (age is not None and age >= 70)
            # Default classification (user can update later)
            voter['classification'] = 'Unclassified'  # Pakka/Virodhi/Swing/Doubtful
            voter['influence_score'] = 0  # 0-10
            voter['contact_count'] = 0
            voter['sentiment'] = 'Neutral'  # Positive/Neutral/Negative/Hostile
            voter['is_beneficiary'] = False
            voter['is_migrated'] = False
            voter['slip_delivered'] = False
            voter['voted'] = False
            voter['notes'] = ''
            voter['tags'] = []          # e.g. ["PM-KISAN", "Ration Card", "Party Worker"]
            voter['caste'] = ''         # explicit caste (overrides surname-inferred community)
            voter['party_lean'] = ''    # BJP/INC/JDS/Other/Unknown

    # ─── ECI Box/Card PDF Parsing ─────────────────────────────────────

    def _parse_box_cells(self, tables_data):
        """Parse ECI voter box cells extracted from PDF tables.
        Each cell/box contains a voter profile with labeled fields.
        Boxes may appear as individual table cells or merged rows.
        """
        for row in tables_data:
            if not row:
                continue
            for cell in row:
                if not cell:
                    continue
                cell_text = str(cell).strip()
                if len(cell_text) < 10:
                    continue
                # Check if this cell looks like a voter box (has a number + name-like content)
                voter = self._extract_voter_from_box(cell_text)
                if voter:
                    self.voters.append(voter)

        # If table cells didn't have individual voter boxes, try row-based
        if not self.voters:
            self._parse_table_data(tables_data)

    def _extract_voter_from_box(self, text):
        """Extract voter data from a single box/cell text block.
        ECI box format typically:
            1
            Name: Rajesh Kumar / नाम: राजेश कुमार
            Father's Name: Ram Prasad / पिता का नाम: ...
            House No: 45 / मकान नं: 45
            Age: 42 / आयु: 42
            Sex: Male / लिंग: पुरुष
            EPIC: XXX1234 (partial)
        """
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if not lines:
            return None

        voter = {
            'sr_no': '', 'name': '', 'father_name': '', 'age': None,
            'gender': None, 'voter_id': '', 'house_no': '', 'address': '',
            'part_no': self.metadata.get('part_no', '')
        }

        full_text = ' '.join(lines)

        # ─── Serial Number ───
        # Usually first number in the box or labeled
        sr_match = re.match(r'^(\d{1,4})\b', lines[0])
        if sr_match:
            voter['sr_no'] = sr_match.group(1)
        else:
            sr_match = re.search(r'(?:S\.?\s*No|क्र(?:म)?(?:ांक)?|Serial)[.\s:]*(\d{1,4})', full_text, re.IGNORECASE)
            if sr_match:
                voter['sr_no'] = sr_match.group(1)

        # ─── Name (English & Hindi labels) ───
        name_patterns = [
            r"(?:Elector(?:'s)?\s*Name|Name\s*of\s*(?:Elector|Voter)|(?:Voter\s*)?Name)[:\s]+([A-Za-z\s.]+?)(?:\n|$|Father|Husband|पिता|पति)",
            r"(?:नाम|निर्वाचक\s*(?:का\s*)?नाम)[:\s]+(.+?)(?:\n|$|पिता|पति)",
            r"(?:Name)[:\s]*([A-Za-z\s.]{3,50})",
        ]
        for pat in name_patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                voter['name'] = re.sub(r'\s+', ' ', m.group(1)).strip()
                # Remove trailing keywords that might have been captured
                voter['name'] = re.sub(r'\s*(Father|Husband|House|Age|Sex|पिता|पति|मकान|आयु|लिंग).*$', '', voter['name'], flags=re.IGNORECASE).strip()
                break

        # If no labeled name found, try to get it from position (2nd or 3rd line after S.No)
        if not voter['name'] and len(lines) >= 2:
            for line in lines[1:4]:
                # Skip lines that are clearly labels or numbers
                clean = re.sub(r'^[\d.)\s]+', '', line).strip()
                if clean and len(clean) > 2 and not re.match(r'^(Father|House|Age|Sex|EPIC|Photo|पिता|मकान|आयु|लिंग)', clean, re.IGNORECASE):
                    if re.match(r'^[A-Za-z\s.]+$', clean) or re.match(r'^[\u0900-\u097F\s]+$', clean):
                        voter['name'] = clean
                        break

        # ─── Father/Husband Name ───
        father_patterns = [
            r"(?:Father(?:'s)?|Husband(?:'s)?|Mother(?:'s)?|Guardian(?:'s)?)\s*(?:Name)?[:\s]+([A-Za-z\s.]+?)(?:\n|$|House|Age|Sex|मकान|आयु|लिंग)",
            r"(?:पिता|पति|माता|अभिभावक)\s*(?:का\s*नाम|नाम)?[:\s]+(.+?)(?:\n|$|मकान|आयु|लिंग)",
            r"(?:F/?H\s*Name|Rel(?:ation)?\s*Name)[:\s]+([A-Za-z\s.]+?)(?:\n|$|House|Age)",
        ]
        for pat in father_patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                voter['father_name'] = re.sub(r'\s+', ' ', m.group(1)).strip()
                voter['father_name'] = re.sub(r'\s*(House|Age|Sex|मकान|आयु|लिंग).*$', '', voter['father_name'], flags=re.IGNORECASE).strip()
                break

        # ─── House Number ───
        house_patterns = [
            r"(?:House\s*(?:No|Number|#)|मकान\s*(?:नं|संख्या|नम्बर)|H\.?\s*No|Door\s*No)[.\s:]*([A-Za-z0-9\-/]+)",
        ]
        for pat in house_patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                voter['house_no'] = m.group(1).strip()
                break

        # ─── Age ───
        age_patterns = [
            r"(?:Age|आयु|उम्र)[:\s]*(\d{2,3})",
            r"\b(\d{2,3})\s*(?:वर्ष|Years?|Yrs?)\b",
        ]
        for pat in age_patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                age_val = int(m.group(1))
                if 18 <= age_val <= 120:
                    voter['age'] = age_val
                    break

        # ─── Gender/Sex ───
        gender_patterns = [
            r"(?:Sex|Gender|लिंग)[:\s]*(Male|Female|M|F|Other|पुरुष|महिला|अन्य)",
            r"\b(Male|Female|पुरुष|महिला)\b",
        ]
        for pat in gender_patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                voter['gender'] = self._norm_gender(m.group(1))
                break

        # ─── Voter ID / EPIC (partial or full) ───
        epic_patterns = [
            r"(?:EPIC|Photo\s*(?:ID|Card)|Voter\s*ID|ID\s*Card|Card\s*No|पहचान\s*पत्र)[.\s:#]*([A-Z]{0,3}\d{4,10})",
            r"\b([A-Z]{2,3}\d{6,7})\b",  # Full EPIC like ABC1234567
            r"(?:EPIC|ID)[.\s:#]*(\d{4,7})",  # Partial - just digits
        ]
        for pat in epic_patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                voter['voter_id'] = m.group(1).strip().upper()
                break

        # Validate: must have at least a name or serial to count as valid voter
        if not voter['name'] and not voter['sr_no']:
            return None
        if voter['name'] and len(voter['name']) < 2:
            return None

        return voter

    def _parse_eci_box_text(self, text):
        """Parse ECI box format from extracted text.
        Boxes in text appear as repeated patterns separated by serial numbers.
        Each voter block starts with a number (1, 2, 3...) followed by their details.
        """
        # Split text into voter blocks by serial numbers at start of "boxes"
        # Pattern: a number at line start (or after whitespace) that starts a new voter
        blocks = re.split(r'\n\s*(?=\d{1,4}\s*[\n.])', text)

        for block in blocks:
            block = block.strip()
            if not block or len(block) < 15:
                continue

            voter = self._extract_voter_from_box(block)
            if voter and voter['name']:
                self.voters.append(voter)

        # If block splitting didn't work well, try a different split strategy
        if len(self.voters) < 3:
            self.voters.clear()
            # Try splitting by repeating label patterns
            # Each voter section has "Name:" or "नाम:" 
            parts = re.split(r'(?=(?:Elector|Voter)(?:\'s)?\s*Name|(?=नाम\s*:))', text, flags=re.IGNORECASE)
            for i, part in enumerate(parts):
                if not part.strip():
                    continue
                # Prepend serial if we can find one nearby
                sr_match = re.search(r'(\d{1,4})\s*$', parts[i-1] if i > 0 else '')
                if sr_match:
                    part = sr_match.group(1) + '\n' + part
                voter = self._extract_voter_from_box(part)
                if voter and voter['name']:
                    if not voter['sr_no']:
                        voter['sr_no'] = str(len(self.voters) + 1)
                    self.voters.append(voter)

    def _parse_table_data(self, tables_data):
        """Parse structured PDF table rows (columnar format)"""
        header_idx = -1
        for i, row in enumerate(tables_data):
            if row and any(cell and any(w in str(cell).lower()
                          for w in ['name', 'नाम', 'elector', 'voter'])
                          for cell in row if cell):
                header_idx = i
                break

        if header_idx == -1:
            self._parse_raw_table(tables_data)
            return

        header = [str(c).lower().strip() if c else '' for c in tables_data[header_idx]]
        col_idx = {}
        for idx, col in enumerate(header):
            if any(w in col for w in ['sr', 'sl', 'क्र', '#', 'no']):
                col_idx.setdefault('sr_no', idx)
            elif any(w in col for w in ['father', 'husband', 'पिता', 'पति', 'relation']):
                col_idx['father_name'] = idx
            elif any(w in col for w in ['name', 'नाम', 'elector']):
                col_idx.setdefault('name', idx)
            elif any(w in col for w in ['age', 'आयु']):
                col_idx['age'] = idx
            elif any(w in col for w in ['sex', 'gender', 'लिंग']):
                col_idx['gender'] = idx
            elif any(w in col for w in ['epic', 'voter id', 'card', 'photo']):
                col_idx['voter_id'] = idx
            elif any(w in col for w in ['house', 'मकान', 'door']):
                col_idx['house_no'] = idx
            elif any(w in col for w in ['address', 'पता']):
                col_idx['address'] = idx

        for row in tables_data[header_idx + 1:]:
            if not row or all(not c for c in row):
                continue
            cells = [str(c).strip() if c else '' for c in row]
            name = cells[col_idx['name']] if 'name' in col_idx and col_idx['name'] < len(cells) else ''
            if not name or name.isdigit():
                continue

            age = None
            if 'age' in col_idx and col_idx['age'] < len(cells):
                try:
                    age = int(re.sub(r'[^\d]', '', cells[col_idx['age']]))
                except (ValueError, TypeError):
                    pass

            self.voters.append({
                'sr_no': cells[col_idx.get('sr_no', 0)] if 'sr_no' in col_idx else str(len(self.voters) + 1),
                'name': name,
                'father_name': cells[col_idx['father_name']] if 'father_name' in col_idx and col_idx['father_name'] < len(cells) else '',
                'age': age,
                'gender': self._norm_gender(cells[col_idx['gender']] if 'gender' in col_idx and col_idx['gender'] < len(cells) else ''),
                'voter_id': (cells[col_idx['voter_id']] if 'voter_id' in col_idx and col_idx['voter_id'] < len(cells) else '').upper(),
                'house_no': cells[col_idx['house_no']] if 'house_no' in col_idx and col_idx['house_no'] < len(cells) else '',
                'address': cells[col_idx['address']] if 'address' in col_idx and col_idx['address'] < len(cells) else '',
                'part_no': self.metadata.get('part_no', ''),
            })

    def _parse_raw_table(self, tables_data):
        """Parse table rows without headers"""
        for row in tables_data:
            if not row or len(row) < 3:
                continue
            cells = [str(c).strip() if c else '' for c in row]
            voter = {'sr_no': '', 'name': '', 'father_name': '', 'age': None,
                     'gender': None, 'voter_id': '', 'house_no': '', 'address': '',
                     'part_no': self.metadata.get('part_no', '')}
            for cell in cells:
                if not cell:
                    continue
                if re.match(r'^[A-Z]{2,3}\d{4,7}$', cell):
                    voter['voter_id'] = cell
                elif re.match(r'^\d{2,3}$', cell) and not voter['age']:
                    age_val = int(cell)
                    if 18 <= age_val <= 120:
                        voter['age'] = age_val
                elif cell.upper() in ('M', 'F', 'MALE', 'FEMALE', 'पुरुष', 'महिला'):
                    voter['gender'] = self._norm_gender(cell)
                elif not voter['name'] and len(cell) > 2 and cell[0].isalpha():
                    voter['name'] = cell
                elif voter['name'] and not voter['father_name'] and cell[0].isalpha():
                    voter['father_name'] = cell
            if voter['name']:
                self.voters.append(voter)

    # ─── Text Parsing ───────────────────────────────────────────────

    def _parse_eci_text(self, text):
        """Parse ECI text patterns — handles both inline and multi-line voter entries"""
        # Pattern 1: ECI box-style where fields are on separate lines
        # Attempt to find voters by "Name:" label patterns
        voter_blocks = re.split(r'\n\s*(\d{1,4})\s*[\n.]', text)
        if len(voter_blocks) > 5:
            for i in range(1, len(voter_blocks) - 1, 2):
                sr_no = voter_blocks[i].strip()
                block = voter_blocks[i + 1] if i + 1 < len(voter_blocks) else ''
                voter = self._extract_voter_from_box(f"{sr_no}\n{block}")
                if voter and voter['name']:
                    self.voters.append(voter)

        if self.voters:
            return

        # Pattern 2: Inline format — No. Name Father/Husband Age Gender EPIC
        pattern = re.compile(
            r'(\d{1,4})\s*[.\)]\s*'
            r'(?:Name[:\s]*)?([A-Za-z\s.]{3,40}?)\s*'
            r'(?:(?:Father|Husband|Mother|Guardian)[\'s ]*(?:Name)?[:\s]*)([A-Za-z\s.]{3,40}?)\s*'
            r'(?:Age[:\s]*)?(\d{2,3})\s*'
            r'(?:(?:Sex|Gender)[:\s]*)?(Male|Female|M|F|Other|पुरुष|महिला)\s*'
            r'(?:(?:EPIC|Photo\s*ID|ID|Card)[.\s:#]*)?([A-Z]{0,3}\d{4,10})?',
            re.IGNORECASE
        )
        for m in pattern.finditer(text):
            age_val = int(m.group(4))
            if age_val < 18 or age_val > 120:
                continue
            self.voters.append({
                'sr_no': m.group(1).strip(),
                'name': m.group(2).strip(),
                'father_name': m.group(3).strip(),
                'age': age_val,
                'gender': self._norm_gender(m.group(5)),
                'voter_id': (m.group(6) or '').strip().upper(),
                'house_no': '', 'address': '',
                'part_no': self.metadata.get('part_no', ''),
            })

        if not self.voters:
            # Pattern 3: Simpler — Number Name Age Gender
            for m in re.finditer(r'(\d{1,4})\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s+(\d{2,3})\s+(M|F|Male|Female)', text):
                age_val = int(m.group(3))
                if age_val < 18 or age_val > 120:
                    continue
                self.voters.append({
                    'sr_no': m.group(1), 'name': m.group(2),
                    'father_name': '', 'age': age_val,
                    'gender': self._norm_gender(m.group(4)),
                    'voter_id': '', 'house_no': '', 'address': '',
                    'part_no': self.metadata.get('part_no', ''),
                })

        if not self.voters:
            self._parse_lines(text)

    def _parse_lines(self, text):
        """Fallback line parser"""
        for i, line in enumerate(text.strip().split('\n')):
            line = line.strip()
            if not line or line[0] in '#-=':
                continue
            parts = re.split(r'[,\t|]+', line)
            if len(parts) < 2:
                continue
            voter = {'sr_no': str(i + 1), 'name': parts[0].strip(), 'father_name': parts[1].strip() if len(parts) > 1 else '',
                     'age': None, 'gender': None, 'voter_id': '', 'house_no': '', 'address': '',
                     'part_no': self.metadata.get('part_no', '')}
            for p in parts[2:]:
                p = p.strip()
                if re.match(r'^\d{2,3}$', p):
                    voter['age'] = int(p)
                elif p.upper() in ('M', 'F', 'MALE', 'FEMALE', 'OTHER'):
                    voter['gender'] = self._norm_gender(p)
                elif re.match(r'^[A-Z]{3}\d{7}$', p.upper()):
                    voter['voter_id'] = p.upper()
            if voter['name'] and voter['name'][0].isalpha():
                self.voters.append(voter)

    # ─── Helpers ────────────────────────────────────────────────────

    def _extract_metadata(self, text):
        # ── Basic fields (labeled formats like "State: Karnataka\n") ──
        # These use \n-terminated patterns — work for text PDFs with clean lines
        for key, pat in [
            ('state', r'(?:State|राज्य)[:\s-]+([A-Za-z\s]+?)(?:\n|$)'),
            ('district', r'(?:District|जिला)[:\s-]+([A-Za-z\s]+?)(?:\n|$)'),
            ('ac_no', r'(?:AC\s*No|विधानसभा\s*क्र)[.:\s-]+(\d+)'),
            ('part_no', r'(?:Part\s*No|भाग\s*(?:सं|संख्या))[.:\s-]+(\d+)'),
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                self.metadata[key] = m.group(1).strip()

        # ── ECI Electoral Roll Cover Page (Page 1) ──
        # Called separately from parse_pdf_stream with high-quality OCR text,
        # but also run here as fallback for text PDFs / CSV / TXT
        self._extract_page1_details(text)

    def _extract_page1_details(self, text, fill_only=False):
        """Extract all details from ECI electoral roll cover page (page 1).
        
        When fill_only=True, only set metadata fields that are still None.
        This allows a second pass (e.g. higher DPI OCR) to fill in values
        that were missed, without overwriting good values from the first pass.
        """
        t = text  # shorthand

        def _set(key, val):
            """Set metadata[key] = val, respecting fill_only mode."""
            if val is None:
                return
            if fill_only and self.metadata.get(key) is not None:
                return
            self.metadata[key] = val

        # ── Roll Year ──
        m = re.search(r'ELECTORAL\s+ROLL\s+(\d{4})', t, re.IGNORECASE)
        if m:
            _set('roll_year', m.group(1))

        # ── State (from "ELECTORAL ROLL 2024 S10 Karnataka") ──
        m = re.search(r'ELECTORAL\s+ROLL\s+\d{4}\s+\S+\s+([A-Za-z\s]+?)(?:\s*No\.|\s*$)', t, re.IGNORECASE)
        if m:
            _set('state', m.group(1).strip())

        # ── Assembly Constituency (No, Name, Reservation) ──
        m = re.search(
            r'(?:Assembly\s+Constituency|AC\s+No\s+and\s+Name)\s*[:\s]+(\d+)\s*[-–]\s*([A-Za-z\s.]+?)(?:\s*\((\w+)\))?(?:\s|$|\n)',
            t, re.IGNORECASE
        )
        if m:
            _set('ac_no', m.group(1).strip())
            _set('assembly', f"{m.group(1).strip()} - {m.group(2).strip()}")
            if m.group(3):
                _set('reservation_status_ac', m.group(3).strip())

        # ── Parliamentary Constituency ──
        m = re.search(
            r'Parliamentary\s+Constituency.*?[:\s]+(\d+)\s*[-–]?\s*([A-Za-z\s.]+?)(?:\s*\((\w+)\))?(?:\s|$|\n)',
            t, re.IGNORECASE
        )
        if m:
            _set('pc_no', m.group(1).strip())
            _set('parliamentary_constituency', f"{m.group(1).strip()} - {m.group(2).strip()}")
            if m.group(3):
                _set('reservation_status_pc', m.group(3).strip())

        # ── Part No (fallback) ──
        m = re.search(r'Part\s*No\.?\s*[:\s]+(\d+)', t, re.IGNORECASE)
        if m:
            _set('part_no', m.group(1).strip())

        # ── Revision Details ──
        all_dates = re.findall(r'(\d{2}-\d{2}-\d{4})', t)
        if all_dates:
            _set('qualifying_date', all_dates[0])
            if len(all_dates) >= 2:
                _set('date_of_updation', all_dates[1])

        m = re.search(r'(?:Type\s+of\s+revision\s+.*?)?(Special\s+Summary\s+Revision\s*\d{0,4}|Summary\s+Revision\s*\d{0,4}|Continuous\s+Updation)', t, re.IGNORECASE)
        if m:
            _set('revision_type', m.group(1).strip())

        m = re.search(r'Roll\s+Identification\s+(.*?)(?:\d\.\s|$)', t, re.IGNORECASE | re.DOTALL)
        if m:
            _set('roll_identification', re.sub(r'\s+', ' ', m.group(1)).strip()[:200])

        # ── Section Details ──
        m = re.search(r'(?:sections?\s+in\s+the\s+part|Section\s+No\s+and\s+Name)\s*[:\s]*([\w\-.]+.*?)(?:\d{3}-NRI|999-|Polling\s+station|\n\d\.|$)', t, re.IGNORECASE)
        if m:
            _set('section_no_name', re.sub(r'\s+', ' ', m.group(1)).strip()[:200])

        # ── Polling Station ──
        m = re.search(r'(?:No\.?\s*and\s*)?Name\s+of\s+Polling\s+Station\s*[:\s]+(.+?)(?:\n|Address|$)', t, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            _set('polling_station', val)
            pm = re.match(r'^(\d+)\s*[-–]\s*(.+)', val)
            if pm:
                _set('part_no', pm.group(1))

        m = re.search(r'Address\s+of\s+Polling\s+Station\s*[:\s]+(.+?)(?:\n|\d\.\s|Main\s+Town|NUMBER|$)', t, re.IGNORECASE)
        if m:
            _set('polling_station_address', re.sub(r'\s+', ' ', m.group(1)).strip()[:200])

        # ── Location Details ──
        # Try the colon-separated block first: ": KHAJURI : KHAJURI S.O : ALAND ..."
        loc_block = re.search(
            r'(?:Pin\s*code|Tehsil|District).*?'
            r':\s*([A-Za-z\s.]+?)\s*'   # village
            r':\s*([A-Za-z\s.]+?)\s*'    # post office
            r':\s*([A-Za-z\s.]+?)\s*'    # police station
            r':\s*([A-Za-z\s.]+?)\s*'    # tehsil
            r':\s*([A-Za-z\s.]+?)\s*'    # district
            r':\s*(\d{6})',              # pincode
            t, re.IGNORECASE | re.DOTALL
        )
        if loc_block:
            _set('main_village_town', loc_block.group(1).strip())
            _set('post_office', loc_block.group(2).strip())
            _set('police_station', loc_block.group(3).strip())
            _set('tehsil', loc_block.group(4).strip())
            _set('district', loc_block.group(5).strip())
            _set('pincode', loc_block.group(6).strip())
        else:
            # Fallback: individual patterns
            m = re.search(r'(?:Main\s+(?:Town|Village)\s+(?:or\s+(?:Village|Town))?).*?:\s*([A-Za-z\s]+?)(?:\s*:|$|\n)', t, re.IGNORECASE)
            if m:
                _set('main_village_town', m.group(1).strip())

        if not self.metadata.get('pincode'):
            m = re.search(r'Pin\s*code[:\s]*(\d{6})', t, re.IGNORECASE)
            if m:
                _set('pincode', m.group(1))

        if not self.metadata.get('district'):
            m = re.search(r'(?:District|जिला)\s*[:\s]+([A-Za-z\s]+?)(?:\s*:|$|\n)', t, re.IGNORECASE)
            if m:
                _set('district', m.group(1).strip())

        # Polling station type
        m = re.search(r'(?:Third\s+Gender)\s+(GENERAL|General|MALE|FEMALE|Male|Female)', t, re.IGNORECASE)
        if m:
            _set('polling_station_type', m.group(1).strip().title())
        elif re.search(r'\bGENERAL\b', t):
            _set('polling_station_type', 'General')

        # Auxiliary polling stations
        m = re.search(r'Auxiliary\s+Polling\s+Station[^:]*?:\s*(\d+)\s', t, re.IGNORECASE)
        if m:
            _set('auxiliary_polling_stations', m.group(1))

        # ── Net Electors ──
        elector_block = re.search(
            r'Net\s+Electors(.{0,500}?)(?:Signature|Electoral\s+Registration|Total\s+[Pp]ages)',
            t, re.IGNORECASE | re.DOTALL
        )
        if elector_block:
            eb = elector_block.group(1)
            m = re.search(r'Male\s+(\d{2,})', eb)
            if m:
                _set('net_electors_male', int(m.group(1)))
            m = re.search(r'Female\s+(\d{2,})', eb)
            if m:
                _set('net_electors_female', int(m.group(1)))
            m = re.search(r'Third\s+Gender\s+(\d+)', eb, re.IGNORECASE)
            if m:
                _set('net_electors_third_gender', int(m.group(1)))
            m = re.search(r'Total\s+(\d{2,})', eb)
            if m:
                _set('net_electors_total', int(m.group(1)))
            m = re.search(r'Starting\s+Serial\s*(?:NO|No)\.?\s*(\d+)', eb, re.IGNORECASE)
            if m:
                _set('starting_serial_no', int(m.group(1)))
            m = re.search(r'Ending\s+Serial\s*(?:NO|No)\.?\s*(\d+)', eb, re.IGNORECASE)
            if m:
                _set('ending_serial_no', int(m.group(1)))

        m = re.search(r'Total\s+pages?\s+(\d+)', t, re.IGNORECASE)
        if m:
            _set('total_pages_in_roll', int(m.group(1)))

    def _map_columns(self, fieldnames):
        col_map = {}
        for f in fieldnames:
            fl = f.lower().strip()
            if fl in ('sr', 'sr no', 'sl no', 'serial', 'sno', 's.no', 'sr.no', 'no', '#', 'id'):
                col_map['sr_no'] = f
            elif fl in ('name', 'voter name', 'elector name', 'voter_name'):
                col_map['name'] = f
            elif fl in ('father', 'father name', 'father/husband', 'father/husband name', 'relation name', 'father_name', 'husband name', 'guardian'):
                col_map['father_name'] = f
            elif fl in ('age', 'voter age'):
                col_map['age'] = f
            elif fl in ('gender', 'sex', 'm/f'):
                col_map['gender'] = f
            elif fl in ('voter id', 'epic', 'epic no', 'voter_id', 'card no'):
                col_map['voter_id'] = f
            elif fl in ('house no', 'house', 'house number', 'door no', 'hno'):
                col_map['house_no'] = f
            elif fl in ('address', 'voter address'):
                col_map['address'] = f
            elif fl in ('part', 'part no', 'part_no', 'section'):
                col_map['part_no'] = f
        return col_map

    def _extract_csv_row(self, row, col_map, idx):
        name = row.get(col_map.get('name', ''), '').strip()
        if not name:
            return None
        age = None
        age_str = row.get(col_map.get('age', ''), '').strip()
        if age_str:
            try:
                age = int(re.sub(r'[^\d]', '', age_str))
            except (ValueError, TypeError):
                pass
        return {
            'sr_no': row.get(col_map.get('sr_no', ''), str(idx)).strip() or str(idx),
            'name': name,
            'father_name': row.get(col_map.get('father_name', ''), '').strip(),
            'age': age,
            'gender': self._norm_gender(row.get(col_map.get('gender', ''), '')),
            'voter_id': row.get(col_map.get('voter_id', ''), '').strip().upper(),
            'house_no': row.get(col_map.get('house_no', ''), '').strip(),
            'address': row.get(col_map.get('address', ''), '').strip(),
            'part_no': row.get(col_map.get('part_no', ''), '').strip() or self.metadata.get('part_no', ''),
        }

    def _norm_gender(self, val):
        if not val:
            return None
        v = val.upper().strip()
        if v in ('M', 'MALE', 'MAL', 'MALO', 'पुरुष'):
            return 'Male'
        if v in ('F', 'FEMALE', 'FEMA', 'FEMAL', 'FEMALO', 'FAMALE', 'महिला'):
            return 'Female'
        if v.startswith('MAL'):
            return 'Male'
        if v.startswith('FEM') or v.startswith('FAM'):
            return 'Female'
        if v in ('O', 'OTHER', 'THIRD GENDER', 'TRANSGENDER', 'अन्य'):
            return 'Other'
        return None
