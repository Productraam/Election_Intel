"""
Election Intelligence - Analytics Engine
Provides booth-level strategy analysis, caste arithmetic, strength meters,
winning formula, contact tracking, and election-day features.
"""

from collections import defaultdict, Counter
from datetime import datetime


class ElectionAnalytics:
    """Full election intelligence analytics across all 3 phases"""

    def __init__(self, voters, metadata=None):
        self.voters = voters
        self.metadata = metadata or {}

    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: Core Intelligence
    # ═══════════════════════════════════════════════════════════════

    def get_summary(self):
        """Master summary with all KPIs"""
        total = len(self.voters)
        ages = [v['age'] for v in self.voters if v.get('age')]
        genders = Counter(v['gender'] for v in self.voters if v.get('gender'))

        return {
            'total_voters': total,
            'male_count': genders.get('Male', 0),
            'female_count': genders.get('Female', 0),
            'other_count': genders.get('Other', 0),
            'gender_unknown': total - sum(genders.values()),
            'male_percent': round(genders.get('Male', 0) / total * 100, 1) if total else 0,
            'female_percent': round(genders.get('Female', 0) / total * 100, 1) if total else 0,
            'avg_age': round(sum(ages) / len(ages), 1) if ages else None,
            'min_age': min(ages) if ages else None,
            'max_age': max(ages) if ages else None,
            'median_age': sorted(ages)[len(ages) // 2] if ages else None,
            'age_groups': self._age_groups(),
            'gender_ratio': round(genders.get('Female', 0) / max(genders.get('Male', 1), 1) * 1000),
            'first_time_voters': sum(1 for v in self.voters if v.get('is_first_time')),
            'youth_voters': sum(1 for v in self.voters if v.get('is_youth')),
            'senior_voters': sum(1 for v in self.voters if v.get('is_senior')),
            'families': len(set(v['family_id'] for v in self.voters if v.get('family_id'))),
            'avg_family_size': round(sum(v.get('family_size', 1) for v in self.voters) / total, 1) if total else 0,
            'needs_transport': sum(1 for v in self.voters if v.get('needs_transport')),
            'metadata': self.metadata
        }

    def _age_groups(self):
        groups = {'18-25': 0, '26-35': 0, '36-45': 0, '46-55': 0, '56-65': 0, '66-75': 0, '75+': 0}
        for v in self.voters:
            age = v.get('age')
            if not age:
                continue
            if 18 <= age <= 25: groups['18-25'] += 1
            elif 26 <= age <= 35: groups['26-35'] += 1
            elif 36 <= age <= 45: groups['36-45'] += 1
            elif 46 <= age <= 55: groups['46-55'] += 1
            elif 56 <= age <= 65: groups['56-65'] += 1
            elif 66 <= age <= 75: groups['66-75'] += 1
            elif age > 75: groups['75+'] += 1
        return groups

    def get_gender_by_age(self):
        """Gender distribution per age group"""
        result = defaultdict(lambda: {'Male': 0, 'Female': 0, 'Other': 0})
        for v in self.voters:
            age, gender = v.get('age'), v.get('gender')
            if not age or not gender:
                continue
            if 18 <= age <= 25: result['18-25'][gender] += 1
            elif 26 <= age <= 35: result['26-35'][gender] += 1
            elif 36 <= age <= 45: result['36-45'][gender] += 1
            elif 46 <= age <= 55: result['46-55'][gender] += 1
            elif 56 <= age <= 65: result['56-65'][gender] += 1
            elif 66 <= age <= 75: result['66-75'][gender] += 1
            elif age > 75: result['75+'][gender] += 1
        return dict(result)

    def get_community_analysis(self):
        """Caste/community composition — the core of caste arithmetic"""
        community_count = Counter(v.get('community', 'Unknown') for v in self.voters)
        total = len(self.voters)
        result = []
        for community, count in community_count.most_common():
            result.append({
                'community': community,
                'count': count,
                'percent': round(count / total * 100, 1) if total else 0
            })
        return result

    def get_surname_analysis(self):
        """Surname frequency analysis for community detection"""
        surname_count = Counter(v.get('surname', '') for v in self.voters if v.get('surname'))
        total = len(self.voters)
        result = []
        for surname, count in surname_count.most_common(30):
            community = next((v.get('community') for v in self.voters if v.get('surname') == surname), 'Unknown')
            result.append({
                'surname': surname,
                'count': count,
                'percent': round(count / total * 100, 1),
                'community': community
            })
        return result

    def get_family_analysis(self):
        """Family/household grouping analysis"""
        families = defaultdict(list)
        for v in self.voters:
            fid = v.get('family_id')
            if fid:
                families[fid].append(v)

        size_dist = Counter(len(members) for members in families.values())
        large_families = sorted(
            [(fid, members) for fid, members in families.items() if len(members) >= 4],
            key=lambda x: len(x[1]), reverse=True
        )[:20]

        return {
            'total_families': len(families),
            'size_distribution': dict(size_dist),
            'avg_size': round(sum(len(m) for m in families.values()) / max(len(families), 1), 1),
            'large_families': [
                {
                    'family_id': fid,
                    'size': len(members),
                    'head': members[0]['father_name'] or members[0]['name'],
                    'house_no': members[0].get('house_no', ''),
                    'members': [{'name': m['name'], 'age': m['age'], 'gender': m['gender']} for m in members]
                }
                for fid, members in large_families
            ]
        }

    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: Booth-Level Strategy
    # ═══════════════════════════════════════════════════════════════

    def get_booth_analysis(self):
        """Per-booth/part voter breakdown"""
        booths = defaultdict(lambda: {
            'total': 0, 'male': 0, 'female': 0, 'other': 0,
            'youth': 0, 'senior': 0, 'first_time': 0, 'ages': [],
            'communities': Counter(), 'families': set()
        })

        for v in self.voters:
            booth = v.get('part_no') or 'Unknown'
            booths[booth]['total'] += 1
            if v.get('gender') == 'Male': booths[booth]['male'] += 1
            elif v.get('gender') == 'Female': booths[booth]['female'] += 1
            else: booths[booth]['other'] += 1
            if v.get('is_youth'): booths[booth]['youth'] += 1
            if v.get('is_senior'): booths[booth]['senior'] += 1
            if v.get('is_first_time'): booths[booth]['first_time'] += 1
            if v.get('age'): booths[booth]['ages'].append(v['age'])
            booths[booth]['communities'][v.get('community', 'Unknown')] += 1
            if v.get('family_id'): booths[booth]['families'].add(v['family_id'])

        result = {}
        for booth, data in booths.items():
            ages = data.pop('ages')
            communities = data.pop('communities')
            families = data.pop('families')
            data['avg_age'] = round(sum(ages) / len(ages), 1) if ages else None
            data['family_count'] = len(families)
            data['top_communities'] = [{'name': c, 'count': n} for c, n in communities.most_common(5)]
            data['gender_ratio'] = round(data['female'] / max(data['male'], 1) * 1000)
            result[booth] = data
        return result

    def get_booth_strength(self):
        """Booth strength meter — classification-based"""
        booths = defaultdict(lambda: {'pakka': 0, 'virodhi': 0, 'swing': 0, 'doubtful': 0, 'unclassified': 0, 'total': 0})
        for v in self.voters:
            booth = v.get('part_no') or 'Unknown'
            cls = v.get('classification', 'Unclassified').lower()
            booths[booth]['total'] += 1
            if cls == 'pakka': booths[booth]['pakka'] += 1
            elif cls == 'virodhi': booths[booth]['virodhi'] += 1
            elif cls == 'swing': booths[booth]['swing'] += 1
            elif cls == 'doubtful': booths[booth]['doubtful'] += 1
            else: booths[booth]['unclassified'] += 1

        result = {}
        for booth, data in booths.items():
            total = data['total']
            data['strength_score'] = round((data['pakka'] / max(total, 1)) * 100, 1)
            data['opposition_score'] = round((data['virodhi'] / max(total, 1)) * 100, 1)
            data['swing_percent'] = round((data['swing'] / max(total, 1)) * 100, 1)
            data['classification_coverage'] = round(((total - data['unclassified']) / max(total, 1)) * 100, 1)
            result[booth] = data
        return result

    def get_winning_formula(self, election_history=None):
        """Winning formula calculator per booth.
        Uses historical turnout if available, otherwise 65% default.
        """
        booths = self.get_booth_strength()

        # Compute effective turnout from history
        hist_turnout = None
        if election_history:
            turnouts = [e.get('turnout_pct', 0) for e in election_history if e.get('turnout_pct')]
            if turnouts:
                hist_turnout = round(sum(turnouts) / len(turnouts), 1)

        turnout_rate = (hist_turnout / 100.0) if hist_turnout else 0.65
        formula = {}
        for booth, data in booths.items():
            total = data['total']
            expected_turnout = int(total * turnout_rate)
            winning_target = (expected_turnout // 2) + 1
            confirmed_votes = data['pakka']
            gap = max(0, winning_target - confirmed_votes)
            swing_available = data['swing']

            formula[booth] = {
                'total_voters': total,
                'turnout_rate_used': round(turnout_rate * 100, 1),
                'turnout_source': 'Historical Avg' if hist_turnout else 'Default (65%)',
                'expected_turnout': expected_turnout,
                'winning_target': winning_target,
                'confirmed_pakka': confirmed_votes,
                'gap_to_win': gap,
                'swing_available': swing_available,
                'swing_needed_percent': round(gap / max(swing_available, 1) * 100, 1),
                'winnable': gap <= swing_available,
                'status': 'SAFE' if confirmed_votes >= winning_target else ('WINNABLE' if gap <= swing_available else 'TOUGH')
            }
        return formula

    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: Field Operations
    # ═══════════════════════════════════════════════════════════════

    def get_panna_pramukh_plan(self):
        """Generate Panna Pramukh assignments (1 worker per 25-30 voters)"""
        booths = defaultdict(list)
        for v in self.voters:
            booths[v.get('part_no') or 'Unknown'].append(v)

        plan = {}
        for booth, voters in booths.items():
            pages = []
            page_size = 25
            for i in range(0, len(voters), page_size):
                page_voters = voters[i:i + page_size]
                pages.append({
                    'page_no': (i // page_size) + 1,
                    'voter_count': len(page_voters),
                    'sr_range': f"{page_voters[0]['sr_no']}-{page_voters[-1]['sr_no']}",
                    'assigned_worker': None,  # To be filled
                    'contact_coverage': 0,
                })
            plan[booth] = {
                'total_voters': len(voters),
                'pages_needed': len(pages),
                'workers_needed': len(pages),
                'pages': pages
            }
        return plan

    def get_contact_coverage(self):
        """Track contact attempts across all voters"""
        total = len(self.voters)
        contacted_1 = sum(1 for v in self.voters if v.get('contact_count', 0) >= 1)
        contacted_2 = sum(1 for v in self.voters if v.get('contact_count', 0) >= 2)
        contacted_3 = sum(1 for v in self.voters if v.get('contact_count', 0) >= 3)

        # Per-booth coverage
        booths = defaultdict(lambda: {'total': 0, 'contacted': 0})
        for v in self.voters:
            booth = v.get('part_no') or 'Unknown'
            booths[booth]['total'] += 1
            if v.get('contact_count', 0) >= 1:
                booths[booth]['contacted'] += 1

        booth_coverage = {}
        for booth, data in booths.items():
            booth_coverage[booth] = round(data['contacted'] / max(data['total'], 1) * 100, 1)

        return {
            'total_voters': total,
            'contacted_once': contacted_1,
            'contacted_twice': contacted_2,
            'contacted_thrice': contacted_3,
            'coverage_percent_1x': round(contacted_1 / max(total, 1) * 100, 1),
            'coverage_percent_2x': round(contacted_2 / max(total, 1) * 100, 1),
            'coverage_percent_3x': round(contacted_3 / max(total, 1) * 100, 1),
            'booth_coverage': booth_coverage
        }

    def get_sentiment_analysis(self):
        """Overall and per-booth sentiment"""
        sentiments = Counter(v.get('sentiment', 'Neutral') for v in self.voters)
        total = len(self.voters)

        booth_sentiments = defaultdict(Counter)
        for v in self.voters:
            booth_sentiments[v.get('part_no') or 'Unknown'][v.get('sentiment', 'Neutral')] += 1

        return {
            'overall': {s: {'count': c, 'percent': round(c / max(total, 1) * 100, 1)} for s, c in sentiments.items()},
            'per_booth': {booth: dict(counts) for booth, counts in booth_sentiments.items()}
        }

    def get_slip_distribution_status(self):
        """Track voter slip delivery"""
        total = len(self.voters)
        delivered = sum(1 for v in self.voters if v.get('slip_delivered'))
        booth_status = defaultdict(lambda: {'total': 0, 'delivered': 0})
        for v in self.voters:
            booth = v.get('part_no') or 'Unknown'
            booth_status[booth]['total'] += 1
            if v.get('slip_delivered'):
                booth_status[booth]['delivered'] += 1

        return {
            'total': total,
            'delivered': delivered,
            'pending': total - delivered,
            'percent': round(delivered / max(total, 1) * 100, 1),
            'per_booth': {b: {'delivered': d['delivered'], 'total': d['total'],
                              'percent': round(d['delivered'] / max(d['total'], 1) * 100, 1)}
                          for b, d in booth_status.items()}
        }

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: Election Day
    # ═══════════════════════════════════════════════════════════════

    def get_polling_day_tracker(self):
        """Live polling day status"""
        total = len(self.voters)
        voted = sum(1 for v in self.voters if v.get('voted'))
        not_voted = total - voted

        booth_status = defaultdict(lambda: {'total': 0, 'voted': 0})
        for v in self.voters:
            booth = v.get('part_no') or 'Unknown'
            booth_status[booth]['total'] += 1
            if v.get('voted'):
                booth_status[booth]['voted'] += 1

        # Priority pickups: pakka voters who haven't voted yet
        priority_pending = [
            {'nqt_id': v['nqt_id'], 'name': v['name'], 'age': v.get('age'),
             'booth': v.get('part_no'), 'needs_transport': v.get('needs_transport'),
             'classification': v.get('classification')}
            for v in self.voters
            if not v.get('voted') and v.get('classification') == 'Pakka'
        ]

        # Transport needed but not voted
        transport_pending = [
            {'nqt_id': v['nqt_id'], 'name': v['name'], 'age': v.get('age'), 'booth': v.get('part_no')}
            for v in self.voters
            if not v.get('voted') and v.get('needs_transport')
        ]

        return {
            'total_voters': total,
            'voted': voted,
            'not_voted': not_voted,
            'turnout_percent': round(voted / max(total, 1) * 100, 1),
            'per_booth': {b: {'total': d['total'], 'voted': d['voted'],
                              'turnout': round(d['voted'] / max(d['total'], 1) * 100, 1)}
                          for b, d in booth_status.items()},
            'pakka_pending_count': len(priority_pending),
            'pakka_pending': priority_pending[:50],
            'transport_pending_count': len(transport_pending),
            'transport_pending': transport_pending[:50]
        }

    def get_turnout_prediction(self):
        """Predict turnout based on demographics"""
        booths = defaultdict(lambda: {'total': 0, 'youth': 0, 'senior': 0, 'female': 0})
        for v in self.voters:
            booth = v.get('part_no') or 'Unknown'
            booths[booth]['total'] += 1
            if v.get('is_youth'): booths[booth]['youth'] += 1
            if v.get('is_senior'): booths[booth]['senior'] += 1
            if v.get('gender') == 'Female': booths[booth]['female'] += 1

        predictions = {}
        for booth, data in booths.items():
            total = data['total']
            # Heuristic: youth turnout ~55%, senior ~70%, female ~60%, avg ~65%
            youth_pct = data['youth'] / max(total, 1)
            senior_pct = data['senior'] / max(total, 1)
            female_pct = data['female'] / max(total, 1)
            predicted = 0.65 - (youth_pct * 0.10) + (senior_pct * 0.05) + (female_pct * 0.02)
            predicted = max(0.50, min(0.80, predicted))
            predictions[booth] = {
                'total_voters': total,
                'predicted_turnout_pct': round(predicted * 100, 1),
                'predicted_votes': int(total * predicted),
                'youth_factor': round(youth_pct * 100, 1),
                'senior_factor': round(senior_pct * 100, 1),
            }
        return predictions

    def get_volunteer_requirement(self):
        """Calculate volunteer needs per booth for election day"""
        booths = defaultdict(int)
        for v in self.voters:
            booths[v.get('part_no') or 'Unknown'] += 1

        result = {}
        for booth, total in booths.items():
            # Need: 1 booth agent + 1 slip distributor + 1 per 100 voters for transport + general workers
            transport_workers = max(1, total // 150)
            result[booth] = {
                'total_voters': total,
                'booth_agents': 2,  # Inside + Outside
                'panna_pramukhs': max(1, total // 25),
                'slip_distributors': max(1, total // 100),
                'transport_coordinators': transport_workers,
                'total_volunteers_needed': 2 + max(1, total // 25) + max(1, total // 100) + transport_workers
            }
        return result

    # ═══════════════════════════════════════════════════════════════
    # Data Quality & Search
    # ═══════════════════════════════════════════════════════════════

    def get_data_quality(self):
        """Data quality audit"""
        total = len(self.voters)
        missing_age = sum(1 for v in self.voters if not v.get('age'))
        missing_gender = sum(1 for v in self.voters if not v.get('gender'))
        missing_vid = sum(1 for v in self.voters if not v.get('voter_id'))
        underage = sum(1 for v in self.voters if v.get('age') and v['age'] < 18)
        very_old = sum(1 for v in self.voters if v.get('age') and v['age'] > 100)

        score = max(0, 100 - (missing_age + missing_gender + underage) / max(total, 1) * 100)

        # Duplicates
        name_age = defaultdict(list)
        for v in self.voters:
            key = f"{v['name'].lower().strip()}-{v.get('age', '')}"
            name_age[key].append(v['nqt_id'])
        dup_groups = {k: v for k, v in name_age.items() if len(v) > 1}

        return {
            'total_voters': total,
            'missing_age': missing_age,
            'missing_gender': missing_gender,
            'missing_voter_id': missing_vid,
            'underage': underage,
            'very_old': very_old,
            'duplicate_groups': len(dup_groups),
            'duplicate_voters': sum(len(v) for v in dup_groups.values()),
            'data_quality_score': round(score, 1)
        }

    def search_voters(self, query, field='name', limit=100):
        """Search voters by field"""
        q = query.strip().lower()
        results = []
        for v in self.voters:
            val = str(v.get(field, '')).lower()
            if q in val:
                results.append(v)
                if len(results) >= limit:
                    break
        return results

    def get_vote_share_simulator(self, pakka_pct=100, swing_capture_pct=50, first_time_pct=60):
        """Simulate vote share under various scenarios"""
        total = len(self.voters)
        classifications = Counter(v.get('classification', 'Unclassified') for v in self.voters)

        pakka = classifications.get('Pakka', 0)
        swing = classifications.get('Swing', 0)
        first_time = sum(1 for v in self.voters if v.get('is_first_time'))

        estimated_votes = (
            int(pakka * pakka_pct / 100) +
            int(swing * swing_capture_pct / 100) +
            int(first_time * first_time_pct / 100)
        )
        expected_turnout = int(total * 0.65)

        return {
            'total_voters': total,
            'expected_turnout': expected_turnout,
            'pakka_votes': int(pakka * pakka_pct / 100),
            'swing_captured': int(swing * swing_capture_pct / 100),
            'first_time_captured': int(first_time * first_time_pct / 100),
            'estimated_total_votes': estimated_votes,
            'estimated_vote_share': round(estimated_votes / max(expected_turnout, 1) * 100, 1),
            'winning_threshold': (expected_turnout // 2) + 1,
            'verdict': 'WIN' if estimated_votes > (expected_turnout // 2) + 1 else 'NEEDS MORE EFFORT'
        }

    # ═══════════════════════════════════════════════════════════════
    # PHASE 4: Aggressive Conversion Strategy
    # ═══════════════════════════════════════════════════════════════

    def get_conversion_funnel(self):
        """Voter conversion funnel — the core strategy dashboard"""
        total = len(self.voters)
        cls = Counter(v.get('classification', 'Unclassified') for v in self.voters)
        contacts = Counter()
        for v in self.voters:
            cc = v.get('contact_count', 0)
            if cc == 0: contacts['no_contact'] += 1
            elif cc == 1: contacts['1_contact'] += 1
            elif cc == 2: contacts['2_contacts'] += 1
            else: contacts['3plus_contacts'] += 1

        # Swing voters needing attention
        swing_voters = [v for v in self.voters if v.get('classification') == 'Swing']
        swing_no_contact = sum(1 for v in swing_voters if v.get('contact_count', 0) == 0)
        swing_1_contact = sum(1 for v in swing_voters if v.get('contact_count', 0) == 1)
        swing_2_contacts = sum(1 for v in swing_voters if v.get('contact_count', 0) == 2)
        swing_3_contacts = sum(1 for v in swing_voters if v.get('contact_count', 0) >= 3)

        # Silent voters (those marked doubtful with 0-1 contacts)
        silent = [v for v in self.voters if v.get('classification') == 'Doubtful' and v.get('contact_count', 0) <= 1]

        # Conversion potential by booth
        booth_potential = defaultdict(lambda: {'swing': 0, 'doubtful': 0, 'unconverted': 0, 'total': 0})
        for v in self.voters:
            booth = v.get('part_no') or 'Unknown'
            booth_potential[booth]['total'] += 1
            c = v.get('classification', 'Unclassified')
            if c == 'Swing': booth_potential[booth]['swing'] += 1
            elif c == 'Doubtful': booth_potential[booth]['doubtful'] += 1
            if c in ('Swing', 'Doubtful') and v.get('contact_count', 0) < 3:
                booth_potential[booth]['unconverted'] += 1

        return {
            'total_voters': total,
            'classified': total - cls.get('Unclassified', 0),
            'pakka': cls.get('Pakka', 0),
            'virodhi': cls.get('Virodhi', 0),
            'swing': cls.get('Swing', 0),
            'doubtful': cls.get('Doubtful', 0),
            'unclassified': cls.get('Unclassified', 0),
            'contact_distribution': dict(contacts),
            'swing_breakdown': {
                'total': len(swing_voters),
                'no_contact': swing_no_contact,
                '1_contact': swing_1_contact,
                '2_contacts': swing_2_contacts,
                '3plus_contacts': swing_3_contacts,
            },
            'silent_voters': len(silent),
            'booth_potential': dict(booth_potential),
        }

    def get_three_contact_plan(self):
        """3-Contact strategy: which voters need which contact number"""
        priority_targets = []
        for v in self.voters:
            cls = v.get('classification', 'Unclassified')
            if cls not in ('Swing', 'Doubtful', 'Unclassified'):
                continue
            cc = v.get('contact_count', 0)
            if cc >= 3:
                continue
            priority = 0
            if cls == 'Swing': priority = 3
            elif cls == 'Doubtful': priority = 2
            else: priority = 1
            # Boost priority for family heads (influence more votes)
            if v.get('family_size', 1) >= 4:
                priority += 2
            priority_targets.append({
                'nqt_id': v.get('nqt_id', ''),
                'name': v['name'],
                'age': v.get('age'),
                'gender': v.get('gender'),
                'booth': v.get('part_no'),
                'classification': cls,
                'contact_count': cc,
                'next_contact': cc + 1,
                'family_size': v.get('family_size', 1),
                'priority': priority,
                'house_no': v.get('house_no', ''),
            })

        priority_targets.sort(key=lambda x: (-x['priority'], x['contact_count']))

        # Summary by contact stage
        stage_counts = {'need_1st': 0, 'need_2nd': 0, 'need_3rd': 0}
        for t in priority_targets:
            if t['contact_count'] == 0: stage_counts['need_1st'] += 1
            elif t['contact_count'] == 1: stage_counts['need_2nd'] += 1
            elif t['contact_count'] == 2: stage_counts['need_3rd'] += 1

        return {
            'total_targets': len(priority_targets),
            'stage_counts': stage_counts,
            'targets': priority_targets[:100],  # Top 100 priority
        }

    def get_family_influence_map(self):
        """Family-unit targeting: identify family heads who control 4+ votes"""
        families = defaultdict(list)
        for v in self.voters:
            fid = v.get('family_id')
            if fid:
                families[fid].append(v)

        influential_families = []
        for fid, members in families.items():
            if len(members) < 3:
                continue
            # Find probable head (oldest male, or oldest member)
            head = sorted(members, key=lambda m: (m.get('gender') != 'Male', -(m.get('age') or 0)))[0]
            cls_counts = Counter(m.get('classification', 'Unclassified') for m in members)
            influential_families.append({
                'family_id': fid,
                'size': len(members),
                'head_name': head['name'],
                'head_age': head.get('age'),
                'head_nqt': head.get('nqt_id', ''),
                'head_classification': head.get('classification', 'Unclassified'),
                'head_contacts': head.get('contact_count', 0),
                'house_no': head.get('house_no', ''),
                'booth': head.get('part_no', ''),
                'classifications': dict(cls_counts),
                'potential_votes': len(members),
            })

        influential_families.sort(key=lambda x: -x['size'])
        return {
            'total_families': len(influential_families),
            'total_potential_votes': sum(f['size'] for f in influential_families),
            'families': influential_families[:50],
        }

    def get_election_day_slots(self):
        """Time-slot based election day plan"""
        voters_by_slot = {'7am_9am': [], '9am_12pm': [], '12pm_3pm': [], '3pm_5pm': []}

        for v in self.voters:
            if v.get('voted'):
                continue
            cls = v.get('classification', 'Unclassified')
            age = v.get('age') or 35

            # Assignment logic:
            # 7-9: Pakka voters (vote early, build momentum)
            # 9-12: Seniors, women, transport-needed
            # 12-3: Remaining pakka who haven't voted
            # 3-5: All swing/doubtful (final push)
            slot_data = {
                'nqt_id': v.get('nqt_id', ''),
                'name': v['name'],
                'age': age,
                'gender': v.get('gender'),
                'booth': v.get('part_no'),
                'classification': cls,
                'needs_transport': v.get('needs_transport', False),
                'house_no': v.get('house_no', ''),
            }

            if cls == 'Pakka' and not v.get('needs_transport'):
                voters_by_slot['7am_9am'].append(slot_data)
            elif v.get('needs_transport') or age >= 60 or v.get('gender') == 'Female':
                voters_by_slot['9am_12pm'].append(slot_data)
            elif cls == 'Pakka':
                voters_by_slot['12pm_3pm'].append(slot_data)
            elif cls in ('Swing', 'Doubtful'):
                voters_by_slot['3pm_5pm'].append(slot_data)
            else:
                voters_by_slot['12pm_3pm'].append(slot_data)

        return {
            'slots': {
                '7am_9am': {'label': '7-9 AM (Pakka First)', 'count': len(voters_by_slot['7am_9am']), 'voters': voters_by_slot['7am_9am'][:30]},
                '9am_12pm': {'label': '9-12 PM (Transport/Seniors)', 'count': len(voters_by_slot['9am_12pm']), 'voters': voters_by_slot['9am_12pm'][:30]},
                '12pm_3pm': {'label': '12-3 PM (Remaining)', 'count': len(voters_by_slot['12pm_3pm']), 'voters': voters_by_slot['12pm_3pm'][:30]},
                '3pm_5pm': {'label': '3-5 PM (Final Push - Swing)', 'count': len(voters_by_slot['3pm_5pm']), 'voters': voters_by_slot['3pm_5pm'][:30]},
            },
            'total_pending': sum(len(s) for s in voters_by_slot.values()),
            'transport_needed': sum(1 for v in self.voters if v.get('needs_transport') and not v.get('voted')),
        }

    def get_caste_strategy(self):
        """Caste arithmetic: which communities to consolidate/split"""
        community_cls = defaultdict(lambda: {'total': 0, 'pakka': 0, 'virodhi': 0, 'swing': 0, 'doubtful': 0})
        for v in self.voters:
            comm = v.get('community', 'Unknown')
            community_cls[comm]['total'] += 1
            cls = v.get('classification', 'Unclassified').lower()
            if cls in ('pakka', 'virodhi', 'swing', 'doubtful'):
                community_cls[comm][cls] += 1

        strategies = []
        for comm, data in community_cls.items():
            total = data['total']
            if total < 3:
                continue
            pakka_pct = round(data['pakka'] / total * 100, 1)
            virodhi_pct = round(data['virodhi'] / total * 100, 1)
            swing_pct = round(data['swing'] / total * 100, 1)

            # Strategy recommendation
            if pakka_pct >= 50:
                strategy = 'CONSOLIDATE'
                action = 'Maintain loyalty, ensure turnout'
            elif virodhi_pct >= 50:
                strategy = 'SPLIT'
                action = 'Find internal divisions, peel off sub-groups'
            elif swing_pct >= 30:
                strategy = 'CONVERT'
                action = 'High-priority conversion, deploy community influencers'
            else:
                strategy = 'ENGAGE'
                action = 'Need classification, increase contact'

            strategies.append({
                'community': comm,
                'total': total,
                'pakka_pct': pakka_pct,
                'virodhi_pct': virodhi_pct,
                'swing_pct': swing_pct,
                'strategy': strategy,
                'action': action,
            })

        strategies.sort(key=lambda x: -x['total'])
        return strategies

    def get_family_tree(self):
        """Build family tree grouped by house number.
        Each house = one family unit. Members linked by relation (father/husband).
        """
        houses = defaultdict(list)
        for v in self.voters:
            house = (v.get('house_no') or '').strip()
            if not house:
                house = 'Unknown'
            houses[house].append(v)

        family_trees = []
        for house, members in houses.items():
            if len(members) < 1:
                continue

            # Sort: oldest male first (likely head), then by age desc
            members.sort(key=lambda m: (m.get('gender') != 'Male', -(m.get('age') or 0)))

            # Build relationships
            head = members[0]
            tree_members = []
            for m in members:
                # Determine relation to head
                relation = 'Self'
                rel_name = (m.get('father_name') or '').strip().lower()
                head_name_l = head['name'].strip().lower()

                if m is head:
                    relation = 'Head'
                elif rel_name == head_name_l:
                    # Father/Husband is the head -> child or spouse
                    if m.get('gender') == 'Female' and m.get('relation_type') in ('Husband', None):
                        relation = 'Spouse'
                    else:
                        relation = 'Child'
                elif m.get('father_name') and m.get('father_name').strip().lower() == (head.get('father_name') or '').strip().lower() and m is not head:
                    relation = 'Sibling'
                else:
                    # Check if this person's name is someone else's father_name
                    is_parent_of = [x for x in members if (x.get('father_name') or '').strip().lower() == m['name'].strip().lower() and x is not m]
                    if is_parent_of:
                        relation = 'Parent'
                    else:
                        relation = 'Member'

                tree_members.append({
                    'nqt_id': m.get('nqt_id', ''),
                    'name': m['name'],
                    'age': m.get('age'),
                    'gender': m.get('gender'),
                    'relation': relation,
                    'father_name': m.get('father_name', ''),
                    'classification': m.get('classification', 'Unclassified'),
                    'contact_count': m.get('contact_count', 0),
                    'voted': m.get('voted', False),
                })

            # Family-level stats
            cls_counts = Counter(m['classification'] for m in tree_members)
            family_trees.append({
                'house_no': house,
                'booth': head.get('part_no', ''),
                'size': len(members),
                'head': head['name'],
                'head_age': head.get('age'),
                'members': tree_members,
                'classifications': dict(cls_counts),
                'all_pakka': cls_counts.get('Pakka', 0) == len(members),
                'has_virodhi': cls_counts.get('Virodhi', 0) > 0,
                'contacts_total': sum(m['contact_count'] for m in tree_members),
                'fully_contacted': all(m['contact_count'] >= 3 for m in tree_members),
            })

        family_trees.sort(key=lambda f: -f['size'])
        return {
            'total_houses': len(family_trees),
            'total_voters': sum(f['size'] for f in family_trees),
            'avg_family_size': round(sum(f['size'] for f in family_trees) / max(len(family_trees), 1), 1),
            'largest_family': family_trees[0]['size'] if family_trees else 0,
            'families': family_trees,
        }

    # ═══════════════════════════════════════════════════════════════
    # TAG ANALYTICS & SCHEME COVERAGE
    # ═══════════════════════════════════════════════════════════════

    def get_tag_analysis(self):
        """Analyze voter tags — counts, per-booth, per-classification."""
        tag_counter = Counter()
        booth_tags = defaultdict(lambda: Counter())
        cls_tags = defaultdict(lambda: Counter())
        tagged_count = 0

        for v in self.voters:
            tags = v.get('tags') or []
            if tags:
                tagged_count += 1
            for tag in tags:
                tag_counter[tag] += 1
                booth_tags[v.get('part_no', 'Unknown')][tag] += 1
                cls_tags[v.get('classification', 'Unclassified')][tag] += 1

        total = len(self.voters)
        tag_list = []
        for tag, count in tag_counter.most_common(50):
            tag_list.append({
                'tag': tag,
                'count': count,
                'percent': round(count / max(total, 1) * 100, 1),
            })

        # Per-booth breakdown for top tags
        top_tags = [t['tag'] for t in tag_list[:10]]
        booth_breakdown = {}
        for booth, tc in booth_tags.items():
            booth_breakdown[booth] = {tag: tc.get(tag, 0) for tag in top_tags}

        # Classification correlation
        cls_breakdown = {}
        for cls, tc in cls_tags.items():
            cls_breakdown[cls] = dict(tc.most_common(10))

        return {
            'total_voters': total,
            'tagged_voters': tagged_count,
            'tagged_percent': round(tagged_count / max(total, 1) * 100, 1),
            'tags': tag_list,
            'booth_breakdown': booth_breakdown,
            'classification_breakdown': cls_breakdown,
        }

    def get_scheme_coverage(self):
        """Analyze scheme beneficiary coverage across booths and communities."""
        scheme_tags = set()
        SCHEME_PREFIXES = ('PM-', 'Ujjwala', 'Awas', 'Ration', 'Pension', 'MNREGA',
                           'Kisan', 'DBT', 'Scholarship', 'BPL', 'APL')
        for v in self.voters:
            for tag in (v.get('tags') or []):
                for prefix in SCHEME_PREFIXES:
                    if tag.lower().startswith(prefix.lower()):
                        scheme_tags.add(tag)
                        break

        booth_scheme = defaultdict(lambda: {'total': 0, 'beneficiaries': 0, 'schemes': Counter()})
        comm_scheme = defaultdict(lambda: {'total': 0, 'beneficiaries': 0, 'schemes': Counter()})

        for v in self.voters:
            booth = v.get('part_no', 'Unknown')
            comm = v.get('caste') or v.get('community', 'Unknown')
            booth_scheme[booth]['total'] += 1
            comm_scheme[comm]['total'] += 1

            voter_schemes = [t for t in (v.get('tags') or []) if t in scheme_tags]
            if voter_schemes or v.get('is_beneficiary'):
                booth_scheme[booth]['beneficiaries'] += 1
                comm_scheme[comm]['beneficiaries'] += 1
                for s in voter_schemes:
                    booth_scheme[booth]['schemes'][s] += 1
                    comm_scheme[comm]['schemes'][s] += 1

        booth_result = {}
        for booth, d in booth_scheme.items():
            booth_result[booth] = {
                'total': d['total'],
                'beneficiaries': d['beneficiaries'],
                'coverage_pct': round(d['beneficiaries'] / max(d['total'], 1) * 100, 1),
                'top_schemes': dict(d['schemes'].most_common(5)),
            }

        comm_result = {}
        for comm, d in comm_scheme.items():
            if d['total'] >= 3:
                comm_result[comm] = {
                    'total': d['total'],
                    'beneficiaries': d['beneficiaries'],
                    'coverage_pct': round(d['beneficiaries'] / max(d['total'], 1) * 100, 1),
                    'top_schemes': dict(d['schemes'].most_common(5)),
                }

        return {
            'total_voters': len(self.voters),
            'total_beneficiaries': sum(d['beneficiaries'] for d in booth_scheme.values()),
            'scheme_types': sorted(scheme_tags),
            'per_booth': booth_result,
            'per_community': dict(sorted(comm_result.items(), key=lambda x: -x[1]['total'])),
        }

    def get_party_lean_analysis(self):
        """Analyze party leanings across voters."""
        party_counter = Counter()
        booth_party = defaultdict(lambda: Counter())
        comm_party = defaultdict(lambda: Counter())

        for v in self.voters:
            lean = v.get('party_lean', '').strip()
            if not lean:
                lean = 'Unknown'
            party_counter[lean] += 1
            booth_party[v.get('part_no', 'Unknown')][lean] += 1
            comm = v.get('caste') or v.get('community', 'Unknown')
            comm_party[comm][lean] += 1

        total = len(self.voters)
        parties = []
        for party, count in party_counter.most_common():
            parties.append({
                'party': party,
                'count': count,
                'percent': round(count / max(total, 1) * 100, 1),
            })

        return {
            'total_voters': total,
            'parties': parties,
            'per_booth': {b: dict(c) for b, c in booth_party.items()},
            'per_community': {c: dict(p) for c, p in comm_party.items() if sum(p.values()) >= 3},
        }

    # ═══════════════════════════════════════════════════════════════
    # HISTORICAL ELECTION ANALYSIS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def get_historical_analysis(election_history):
        """Compute historical trends from election history data."""
        if not election_history:
            return {'has_data': False, 'elections': []}

        elections = sorted(election_history, key=lambda e: e.get('year', 0))

        # Party-wise aggregated trends
        party_totals = defaultdict(lambda: {'total_votes': 0, 'elections': 0, 'wins': 0})
        turnouts = []
        results = []

        for e in elections:
            parties = e.get('parties', [])
            total_votes = e.get('total_votes', 0)
            turnout = e.get('turnout_pct', 0)
            winner = e.get('winner', '')
            if turnout:
                turnouts.append(turnout)

            party_results = []
            for p in parties:
                name = p.get('name', 'Unknown')
                votes = p.get('votes', 0)
                party_totals[name]['total_votes'] += votes
                party_totals[name]['elections'] += 1
                if name == winner:
                    party_totals[name]['wins'] += 1
                share = round(votes / max(total_votes, 1) * 100, 1) if total_votes else 0
                party_results.append({
                    'name': name,
                    'votes': votes,
                    'vote_share': share,
                    'candidate': p.get('candidate', ''),
                })

            results.append({
                'year': e.get('year', ''),
                'election_type': e.get('election_type', ''),
                'total_votes': total_votes,
                'turnout_pct': turnout,
                'winner': winner,
                'parties': sorted(party_results, key=lambda x: -x['votes']),
            })

        # Party strength summary
        party_summary = []
        for name, data in party_totals.items():
            party_summary.append({
                'party': name,
                'total_votes': data['total_votes'],
                'elections_contested': data['elections'],
                'wins': data['wins'],
                'avg_votes': round(data['total_votes'] / max(data['elections'], 1)),
            })
        party_summary.sort(key=lambda x: -x['total_votes'])

        avg_turnout = round(sum(turnouts) / len(turnouts), 1) if turnouts else None

        return {
            'has_data': True,
            'total_elections': len(elections),
            'avg_turnout': avg_turnout,
            'elections': results,
            'party_summary': party_summary,
        }
