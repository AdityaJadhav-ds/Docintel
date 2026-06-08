"""
semantic_parser.py — STABILIZED
================================
Extracts: name, percentage, obtained_marks, total_marks, result
from Maharashtra SSC/HSC marksheet OCR word lists.

Covers all 5 formats:
  - SSC 1988 (old Pune, all caps)
  - SSC 2000 (Kolhapur, teal table)
  - SSC 2020 (new with QR, certificate)
  - HSC 2022 statement (new with QR)
  - HSC 2022 certificate (YCIS / College)

NO new engines. Only smarter extraction from existing OCR output.
"""
import re
from .line_reconstructor import LineReconstructor
from .document_graph import DocumentGraph
from .key_value_linker import KeyValueLinker
from .candidate_ranker import CandidateRanker
from .field_resolver import FieldResolver
from .extraction_confidence import ExtractionConfidence
from .debug_explainer import DebugExplainer
from .table_reasoner import TableReasoner
from .semantic_validators import SemanticValidators
from .name_extractor import NameExtractor


class SemanticParser:
    """Universal Maharashtra SSC/HSC marksheet parser."""

    def __init__(self):
        self.reconstructor = LineReconstructor()
        self.graph_builder = DocumentGraph()
        self.ranker = CandidateRanker()
        self.conf_engine = ExtractionConfidence()
        self.resolver = FieldResolver(self.ranker, self.conf_engine)
        self.explainer = DebugExplainer()
        self.table_reasoner = TableReasoner()
        self.name_extractor = NameExtractor()  # dedicated name module

    # ─────────────────────────────────────────────────────────
    # LABEL DICTIONARIES  (English + Marathi + University)
    # ─────────────────────────────────────────────────────────
    _NAME_LABELS = [
        'full name', 'candidate', 'student', 'surname',
        'नाव', 'उमेदवाराचे', 'certify that', 'name of student',
        'student name', 'name:', 'name of candidate',
    ]
    _PCT_LABELS = [
        'percentage', 'टक्केवारी', 'टकेवारी', 'percent', 'aggregate', '%',
    ]
    _RESULT_LABELS = [
        'result', 'निकाल', 'pass', 'fail', 'distinction',
    ]
    _OBTAINED_LABELS = [
        'marks obtained', 'obtained', 'प्राप्त', 'total marks obtained',
        'marks ob', 'obtained marks',
    ]
    _TOTAL_LABELS = [
        'maximum marks', 'max marks', 'total marks', 'grand total',
        'एकूण', 'कमाल', 'maximum',
    ]
    # University / degree labels
    _CGPA_LABELS   = ['cgpa', 'cumulative gpa', 'cpi', 'overall gpa', 'grade point']
    _SPI_LABELS    = ['spi', 'semester performance', 'semester grade', 'sgpa', 'gpa']
    _URN_LABELS    = ['urn', 'university roll', 'roll no', 'enrollment', 'seat no',
                      'prn', 'registration no', 'student id', 'uid']
    _BRANCH_LABELS = [
        # 'branch' MUST come first — 'program/programme' matches 'Program: B.TECH'
        # which is the program TYPE, not the branch NAME.
        'branch',
        'specialization', 'discipline', 'stream',
        # Only use these if no 'branch' label found
        'department',
    ]
    _YEAR_LABELS   = ['year', 'passing year', 'exam year', 'academic year',
                      'batch', 'session', 'semester']
    _BOARD_LABELS  = ['board', 'university', 'institute', 'college', 'school',
                      'विद्यापीठ', 'बोर्ड']

    # ── Roman numeral map for semester ordering ────────────────────────────
    _ROMAN = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}

    def _parse_roman(self, s: str) -> int:
        return self._ROMAN.get(s.strip().upper(), 0)

    def _extract_academic_metrics(self, text: str) -> dict:
        """
        Scan full text and classify ALL academic metrics.
        Returns: {semester_spis: [{semester, spi}], cpi, cgpa}
        """
        semester_spis = []
        cpi = None
        cgpa = None

        # ── CPI (highest priority cumulative) ──────────────────────────────
        for m in re.finditer(r'\bCPI\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE):
            val = float(m.group(1))
            if 0.0 < val <= 10.0:
                cpi = round(val, 2)
                break

        # ── CGPA ───────────────────────────────────────────────────────────
        for m in re.finditer(r'\bCGPA\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE):
            val = float(m.group(1))
            if 0.0 < val <= 10.0:
                cgpa = round(val, 2)
                break

        # ── Performance Summary row: 'credits SPI total_credits CPI' ───────
        # e.g. '22 8.95 96 8.93'
        perf_start = text.lower().find('performance')
        search_zone = text[perf_start:] if perf_start >= 0 else text[-600:]
        pm = re.search(
            r'\b(\d{1,2})\s+([0-9]\.[0-9]{2})\s+(\d{2,3})\s+([0-9]\.[0-9]{2})\b',
            search_zone
        )
        if pm:
            perf_spi = float(pm.group(2))
            perf_cpi = float(pm.group(4))
            if 0.0 < perf_cpi <= 10.0 and cpi is None:
                cpi = round(perf_cpi, 2)
            if 0.0 < perf_spi <= 10.0:
                semester_spis.append({"semester": 99, "spi": round(perf_spi, 2)})

        # ── All SPI values with semester context ───────────────────────────
        for m in re.finditer(r'\bSPI\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE):
            val = float(m.group(1))
            if not (0.0 < val <= 10.0):
                continue
            context_before = text[max(0, m.start()-120):m.start()]
            # Skip if this looks like a CPI context
            if re.search(r'\b(cumulative|CPI|aggregate|overall)\b', context_before, re.IGNORECASE):
                if cpi is None:
                    cpi = round(val, 2)
                continue
            # Parse semester number
            sem_m = re.search(r'\bsem(?:ester)?\s+([IVXivx]{1,4}|\d+)\b',
                               context_before, re.IGNORECASE)
            sem_num = 0
            if sem_m:
                raw = sem_m.group(1).upper()
                sem_num = int(raw) if raw.isdigit() else self._parse_roman(raw)
            existing_vals = [s["spi"] for s in semester_spis]
            if val not in existing_vals:
                semester_spis.append({"semester": sem_num, "spi": round(val, 2)})

        semester_spis.sort(key=lambda x: x["semester"])
        return {"semester_spis": semester_spis, "cpi": cpi, "cgpa": cgpa}

    def _resolve_display_score(self, metrics: dict):
        """Priority: CPI > CGPA > Latest Semester SPI."""
        if metrics.get("cpi") is not None:
            return {"type": "CPI", "value": metrics["cpi"]}
        if metrics.get("cgpa") is not None:
            return {"type": "CGPA", "value": metrics["cgpa"]}
        spis = metrics.get("semester_spis", [])
        if spis:
            latest = max(spis, key=lambda x: x["semester"])
            return {"type": "SPI", "value": latest["spi"]}
        return None

    def parse(self, ocr_words: list, extra_text: str = "") -> dict:
        if not ocr_words:
            return {"fields": {}, "table_data": {}, "debug_explanation": {}}

        # Step 1: Reconstruct spatial lines
        lines = self.reconstructor.reconstruct(ocr_words)

        # Step 2: Build document spatial graph
        graph = self.graph_builder.build_graph(lines)

        # Step 3: Raw merged text — supplement with native PDF text if provided
        merged_text = " ".join(w['text'] for w in ocr_words)
        if extra_text and extra_text.strip():
            merged_text = merged_text + " " + extra_text.strip()

        # Step 4: Key-value linking via graph relationships (used only for percentage)
        linker = KeyValueLinker(graph)
        pct_candidates = linker.find_values_for_label(self._PCT_LABELS)

        # Step 5: Dedicated name extraction (replaces old graph-based name resolution)
        name_field = self.name_extractor.extract(lines, ocr_words)
        name_debug = name_field.pop('_name_debug', {})

        # Step 6: Percentage — graph candidates then regex fallback
        best_pct,  pct_score,  _ = self.resolver.resolve_percentage(pct_candidates, graph)

        # Step 6b: Regex fallback — ALWAYS run, prefer if graph result is dirty
        regex_pct, regex_score = self._regex_percentage_fallback(merged_text, lines, graph)
        graph_val = best_pct.get('value', '') if best_pct else ''
        graph_is_dirty = bool(re.search(r'[A-Za-z]{3,}', str(graph_val)))
        if best_pct is None or graph_is_dirty:
            if regex_pct is not None:
                best_pct, pct_score = regex_pct, regex_score

        # Step 7: Extract marks and result via regex
        obtained, total = self._extract_marks(merged_text, lines)
        result = self._extract_result(merged_text, lines)

        # Step 8: Academic intelligence — extract all metrics with semantic priority
        academic = self._extract_academic_metrics(merged_text)
        display_score = self._resolve_display_score(academic)
        cpi    = academic["cpi"]
        cgpa   = academic["cgpa"] or self._extract_numeric_field(merged_text, lines, self._CGPA_LABELS, 0.0, 10.0)
        # Latest semester SPI (for backward compat display)
        semester_spis = academic["semester_spis"]
        spi = None
        if semester_spis:
            spi = max(semester_spis, key=lambda x: x["semester"])["spi"]
        branch = self._extract_branch(merged_text, lines)
        year   = self._extract_year_field(merged_text)

        # Step 9: Table data
        table_data = self.table_reasoner.extract_table_data(graph)

        # ── Assemble final fields ──
        final_results = {}

        if name_field.get('value'):
            final_results["name"] = name_field

        if best_pct:
            final_results["percentage"] = self.conf_engine.generate_confidence(best_pct, pct_score)

        if obtained is not None:
            final_results["obtained_marks"] = {
                "value": str(obtained), "confidence": 0.85,
                "extraction_strategy": "regex_marks", "source_label": "marks_table",
                "source_region": (0, 0, 0, 0),
            }

        if total is not None:
            final_results["total_marks"] = {
                "value": str(total), "confidence": 0.85,
                "extraction_strategy": "regex_marks", "source_label": "marks_table",
                "source_region": (0, 0, 0, 0),
            }

        if result:
            final_results["result"] = {
                "value": result, "confidence": 0.90,
                "extraction_strategy": "regex_result", "source_label": "result_field",
                "source_region": (0, 0, 0, 0),
            }

        if cgpa is not None:
            final_results["cgpa"] = {
                "value": str(cgpa), "confidence": 0.88,
                "extraction_strategy": "regex_cgpa", "validated": True,
                "source_region": (0, 0, 0, 0),
            }
        if cpi is not None:
            final_results["cpi"] = {
                "value": str(cpi), "confidence": 0.92,
                "extraction_strategy": "academic_resolver", "validated": True,
                "source_region": (0, 0, 0, 0),
            }
        if spi is not None:
            final_results["spi"] = {
                "value": str(spi), "confidence": 0.90,
                "extraction_strategy": "academic_resolver_latest_sem", "validated": True,
                "source_region": (0, 0, 0, 0),
            }
        if semester_spis:
            # Clean up sem=99 (perf summary source) — give it a real sem number based on position
            clean_sems = [s for s in semester_spis if s["semester"] != 99]
            final_results["semester_scores"] = {
                "value": clean_sems, "confidence": 0.90,
                "extraction_strategy": "academic_resolver", "validated": True,
                "source_region": (0, 0, 0, 0),
            }
        if display_score is not None:
            final_results["display_score"] = {
                "value": display_score, "confidence": 0.95,
                "extraction_strategy": "academic_priority_resolver", "validated": True,
                "source_region": (0, 0, 0, 0),
            }
        if branch:
            final_results["branch"] = {
                "value": branch, "confidence": 0.85,
                "extraction_strategy": "regex_branch", "validated": True,
                "source_region": (0, 0, 0, 0),
            }
        if year:
            final_results["passing_year"] = {
                "value": year, "confidence": 0.88,
                "extraction_strategy": "regex_year", "validated": True,
                "source_region": (0, 0, 0, 0),
            }
        # Board and URN intentionally omitted — not needed for degree marksheets

        # Step 10: Math cross-check — if obtained+total known, compute percentage precisely
        # This fixes OCR digit-swap errors e.g. 82.49 vs actual 82.40 from 412/500
        if obtained is not None and total is not None and total > 0:
            computed_pct = round((obtained / total) * 100, 2)
            if best_pct is not None:
                try:
                    ocr_pct = float(best_pct.get('value', 0))
                    # If computed and OCR values differ by ≤ 1.5%, prefer math result
                    if abs(ocr_pct - computed_pct) <= 1.5:
                        best_pct = {
                            "value": f"{computed_pct:.2f}",
                            "node": {"id": "math_verified", "text": f"{computed_pct:.2f}",
                                     "bbox": (0,0,0,0), "relationships": {}},
                            "source_label": "math_cross_check",
                            "strategy": "obtained_over_total",
                        }
                        pct_score = 11.0  # high confidence for math-verified result
                except (ValueError, TypeError):
                    pass
            elif 30.0 <= computed_pct <= 100.0:
                # No OCR percentage found — compute from marks directly
                best_pct = {
                    "value": f"{computed_pct:.2f}",
                    "node": {"id": "math_fallback", "text": f"{computed_pct:.2f}",
                             "bbox": (0,0,0,0), "relationships": {}},
                    "source_label": "math_cross_check",
                    "strategy": "obtained_over_total",
                }
                pct_score = 9.0

        # Step 11: Final garbage cleanup
        for f in ["branch"]:
            if f in final_results:
                final_results[f]["value"] = self._clean_garbage(final_results[f]["value"])

        # Remove branch from final output (not needed)
        final_results.pop("branch", None)

        # Step 11: Name catch-all (Universal fallback)
        if "name" not in final_results or not final_results["name"].get("value"):
            universal_name = self._universal_name_fallback(merged_text, lines)
            if universal_name:
                final_results["name"] = {
                    "value": universal_name, "confidence": 0.50,
                    "extraction_strategy": "universal_catchall", "source_label": "text_pattern",
                    "source_region": (0, 0, 0, 0),
                }

        return {
            "fields": final_results,
            "table_data": table_data,
            "debug_explanation": {
                **self.explainer.get_logs(),
                "name_pipeline": name_debug,
            },
        }

    def _extract_spi(self, text: str):
        """
        Dedicated SPI extractor for university grade cards.
        Returns the CURRENT SEMESTER (final) SPI.

        Priority order:
          1. Performance Summary table row:  '22  8.95  96  8.93'
             → group(2) = current semester SPI  (MOST AUTHORITATIVE)
          2. Last 'SPI: X.XX' colon pattern (semester headers)
          3. Last 'SPI X.XX' space pattern
        """
        import logging
        _log = logging.getLogger("docvalidator")

        # Log all SPI contexts for debugging
        spi_ctx = [text[max(0, m.start()-15):m.end()+30]
                   for m in re.finditer(r'\bSPI\b', text, re.IGNORECASE)]
        _log.info("[spi_debug] SPI contexts in OCR: %s", spi_ctx)

        # ── Strategy 1 (HIGHEST PRIORITY): Performance Summary row ─────────
        # Pattern: credits(1-2 digits)  SPI(X.XX)  total_credits(2-3 digits)  CPI(X.XX)
        # e.g. '22 8.95 96 8.93'
        # Search near 'performance summary' if present
        perf_start = text.lower().find('performance')
        if perf_start == -1:
            perf_start = max(0, len(text) - 400)   # fallback: last 400 chars
        perf_text = text[perf_start:]

        m = re.search(
            r'\b(\d{1,2})\s+([0-9]\.[0-9]{2})\s+(\d{2,3})\s+([0-9]\.[0-9]{2})\b',
            perf_text
        )
        if m:
            spi_val = float(m.group(2))
            _log.info("[spi_s1] perf-summary: credits=%s SPI=%s total=%s CPI=%s",
                      m.group(1), m.group(2), m.group(3), m.group(4))
            if 0.0 < spi_val <= 10.0:
                _log.info("[spi] FINAL from performance summary: %s", spi_val)
                return round(spi_val, 2)

        # ── Strategy 2: 'SPI: X.XX' colon pattern ──────────────────────────
        matches = re.findall(r'\bSPI\s*:\s*([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE)
        _log.info("[spi_s2] colon-pattern matches: %s", matches)
        if matches:
            vals = [float(v) for v in matches if 0.0 < float(v) <= 10.0]
            if vals:
                _log.info("[spi] FINAL from colon-pattern (last): %s", vals[-1])
                return round(vals[-1], 2)

        # ── Strategy 3: 'SPI X.XX' space pattern ───────────────────────────
        matches = re.findall(r'\bSPI\s+([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE)
        _log.info("[spi_s3] space-pattern matches: %s", matches)
        if matches:
            vals = [float(v) for v in matches if 0.0 < float(v) <= 10.0]
            if vals:
                _log.info("[spi] FINAL from space-pattern (last): %s", vals[-1])
                return round(vals[-1], 2)

        _log.info("[spi] no SPI found")
        return None

    def _extract_branch(self, text: str, lines: list):
        """
        Extract branch/programme name.
        Validates that result looks like a branch name (not 'Examination EVEN...').
        """
        label_re = re.compile(r'\bbranch\b', re.IGNORECASE)
        # A valid branch value: only uppercase letters, spaces, digits
        # e.g. 'ARTIFICIAL INTELLIGENCE AND DATA SCIENCE'
        valid_re = re.compile(r'^[A-Z][A-Z\s&/()]{4,}$')
        # Reject values that contain these label-like words
        reject_re = re.compile(
            r'\b(?:examination|even|odd|urn|semester|year|third|second|first)\b',
            re.IGNORECASE
        )

        for line in lines:
            lt = line['text']
            if label_re.search(lt):
                remainder = label_re.sub('', lt).strip(' :.-')
                if remainder and not reject_re.search(remainder) and len(remainder) >= 5:
                    return remainder

        # Next-line strategy
        prev = False
        for line in lines:
            if label_re.search(line['text']):
                prev = True
                continue
            if prev:
                val = line['text'].strip()
                if val and not reject_re.search(val) and len(val) >= 5:
                    return val
                prev = False

        return None

    def _clean_garbage(self, val: str) -> str:
        """Remove OCR noise: 'f——', '(An Autonomous...) ose763', lone-char prefixes."""
        if not val:
            return val

        # 1. Strip leading single character(s) followed by dashes/equals
        #    e.g. 'f——  TEXT' → 'TEXT',  'f --: TEXT' → 'TEXT'
        val = re.sub(r'^[a-zA-Z]\s*[-=\u2013\u2014]{1,4}\s*', '', val)

        # 2. If value starts with '(' (pure parenthetical garbage), try to rescue
        #    university/college names embedded inside: "(Autonomous affiliated to Shivaji Univ)"
        if val.strip().startswith('('):
            # Look for a proper noun inside the parenthetical
            inner = re.sub(r'[()]', '', val).strip()
            # Try extracting "XYZ University / Board" from inner text
            m = re.search(r'(?:affiliated\s+to\s+|)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:University|Board|Institute))',
                          inner, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
            else:
                # Just strip the parens and trailing garbage
                val = inner

        # 3. Remove parenthetical blocks in the middle/end
        #    e.g. 'Shivaji University (Kolhapur) ose763' → 'Shivaji University'
        val = re.sub(r'\s*\([^)]{5,}\)\s*', ' ', val).strip()

        # 4. Remove trailing alphanumeric garbage tokens
        #    e.g. 'Shivaji University ose763' → 'Shivaji University'
        val = re.sub(r'\s+[a-z]{2,4}\d{2,}\s*$', '', val, flags=re.IGNORECASE)

        # 5. Strip leading/trailing punctuation
        val = val.strip(' :.-_=+/?!@#$%^&*')

        return val.strip()

    def _universal_name_fallback(self, text: str, lines: list) -> str:
        """Catch-all for names that NameExtractor might have missed."""
        _bad = re.compile(
            r'\b(?:board|university|exam|marksheet|result|percentage|grade|'
            r'college|institute|school|statement|certificate|marks|pune|kolhapur|'
            r'mumbai|nashik|nagpur|state|division|divisional|higher|secondary|'
            r'education|msbshse|science|arts|commerce|stream|seat|center|centre|'
            r'district|region|date|year|march|april|may|june|july|august|'
            r'september|october|november|december|january|february)\b',
            re.IGNORECASE
        )
        # Only consider top 20 lines; name is usually in first half
        for line in lines[:20]:
            lt = line['text'].strip()
            if not lt or _bad.search(lt):
                continue
            words = lt.split()
            # Require exactly 3-4 words (Indian names are almost always 3 parts)
            if not (3 <= len(words) <= 4):
                continue
            # Each word must be >= 3 characters (filters fragments like "in", "gard")
            if not all(len(w) >= 3 for w in words):
                continue
            # Pattern 1: 3-4 ALL CAPS words (old SSC style)
            if re.match(r'^[A-Z]{3,}(\s+[A-Z]{3,}){2,3}$', lt):
                return lt
            # Pattern 2: 3-4 TitleCase words (new format) — each word capitalized
            if re.match(r'^[A-Z][a-z]+(\s+[A-Z][a-z]+){2,3}$', lt):
                return lt
        return None

    # ─────────────────────────────────────────────────────────
    # REGEX FALLBACK: PERCENTAGE
    # ─────────────────────────────────────────────────────────
    def _regex_percentage_fallback(self, text: str, lines: list, graph) -> tuple:
        """
        Scan lines for percentage patterns near known labels.
        Returns (candidate_dict, score) or (None, -999).

        Strategy order:
          1. Label + value on same line:  "Percentage 75.17"
          2. Value on line immediately following the label line
          3. Any decimal XX.XX in 0–100 range near the bottom of doc
        """
        pct_label_re = re.compile(
            r'percent|टक्केवारी|टकेवारी|%|aggregate', re.IGNORECASE
        )
        pct_num_re = re.compile(
            r'\b(\d{1,3}[.,]\d{1,2})\b'  # decimal form like 75.17 or 82,40
        )

        def _make_candidate(raw_str, strategy, score):
            # Strip £/$ and trailing % signs
            clean = re.sub(r'[£$€₹%]', '', raw_str).strip().replace(',', '.')
            num = SemanticValidators.extract_percentage_number(clean)
            if num is None:
                return None, -999.0
            cand = {
                "value": f"{num:.2f}",
                "node": {
                    "id": strategy,
                    "text": raw_str,
                    "bbox": (0, 0, 0, 0),
                    "relationships": {
                        "nearest_right": None, "nearest_left": None,
                        "nearest_below": None, "aligned_with": [],
                    },
                },
                "source_label": strategy,
                "strategy": strategy,
            }
            return cand, score

        # ── Strategy 1: label + value on same line ────────────
        for line in lines:
            lt = line['text']
            if pct_label_re.search(lt):
                # Strip the label keywords and look for a decimal number in what remains
                stripped = pct_label_re.sub('', lt)
                m = pct_num_re.search(stripped)
                if m:
                    cand, score = _make_candidate(m.group(1), "regex_same_line", 10.0)
                    if cand:
                        return cand, score

        # ── Strategy 2: value on line after label ─────────────
        label_found = False
        for line in lines:
            lt = line['text']
            if pct_label_re.search(lt):
                label_found = True
                continue
            if label_found:
                m = pct_num_re.search(lt)
                if m:
                    cand, score = _make_candidate(m.group(1), "regex_next_line", 9.0)
                    if cand:
                        return cand, score
                label_found = False  # reset after one skip

        # ── Strategy 3: any decimal in merged text after label ─
        m = re.search(
            r'(?:percent|टकेवारी|%)[^\d]{0,30}[£$]?\s*(\d{1,3}[.,\s]\d{1,2})',
            text, re.IGNORECASE
        )
        if m:
            cand, score = _make_candidate(m.group(1).replace(' ', '.'), "regex_context", 8.0)
            if cand:
                return cand, score

        # ── Strategy 4: find any XX.YY decimal 30–100 ─────────
        # Last resort: any decimal percentage in the document
        all_decimals = re.findall(r'\b(\d{1,3}\.\d{1,2})\b', text)
        for d in all_decimals:
            num = SemanticValidators.extract_percentage_number(d)
            if num is not None and 30.0 <= num <= 100.0:
                cand, score = _make_candidate(d, "regex_last_resort", 5.0)
                if cand:
                    return cand, score

        return None, -999.0

    # ─────────────────────────────────────────────────────────
    # REGEX EXTRACTION: MARKS
    # Strategy: scan line-by-line for rows with known labels
    # In old formats: last number on MARKS OBTAINED row = obtained
    #                 last number on MAXIMUM MARKS row = total
    # In new formats: "Total Marks 600 451" pattern
    # ─────────────────────────────────────────────────────────
    def _extract_marks(self, text: str, lines: list):
        """
        Returns (obtained, total) as floats, or (None, None).
        """
        obtained = None
        total = None

        # ── Strategy 1: New format — "Total Marks 600 451" ──
        # Look for two 3-digit numbers after the total marks label
        m = re.search(
            r'(?:total\s*marks?|एकूण\s*गुण)[^\d]{0,50}(\d{3,4})[^\d]{1,20}(\d{3,4})',
            text, re.IGNORECASE
        )
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            # Larger = total, smaller = obtained
            if a >= b:
                total, obtained = float(a), float(b)
            else:
                total, obtained = float(b), float(a)

        # ── Strategy 2: Old format — scan lines for MARKS OBTAINED row ──
        # "MARKS OBTAINED 035 047 035 052 057 035 261"
        # The LAST number on this row is the grand total obtained
        if obtained is None:
            for line in lines:
                lt = line['text'].upper()
                if 'OBTAINED' in lt and 'MARKS' in lt:
                    nums = re.findall(r'\b(\d{2,4})\b', line['text'])
                    if nums:
                        obtained = float(nums[-1])  # last = grand total

        # ── Strategy 3: Old format — MAXIMUM MARKS row ──
        # "MAXIMUM MARKS 100 100 100 150 150 100 700"
        # Last number = total marks
        if total is None:
            for line in lines:
                lt = line['text'].upper()
                if ('MAXIMUM' in lt and 'MARKS' in lt) or ('GRAND' in lt and 'TOTAL' in lt):
                    nums = re.findall(r'\b(\d{3,4})\b', line['text'])
                    # The last 3+ digit number is total
                    totals = [int(n) for n in nums if int(n) >= 100]
                    if totals:
                        total = float(max(totals))  # largest = total marks

        # ── Strategy 4: SSC 2020 cert format — "500 £407+05" ──
        # "एकूण गुण/Total Marks 500 £407+05"
        if total is None or obtained is None:
            m = re.search(
                r'(?:total|एकूण)[^\d]{0,30}(\d{3,4})[^\d£$]{0,10}[£$]?(\d{3,4})(?:\+(\d{1,3}))?',
                text, re.IGNORECASE
            )
            if m:
                a = int(m.group(1))
                b = int(m.group(2))
                grace = int(m.group(3)) if m.group(3) else 0
                b_adj = b + grace
                if total is None:
                    total = float(max(a, b_adj))
                if obtained is None:
                    obtained = float(min(a, b_adj))

        return obtained, total

    # ─────────────────────────────────────────────────────────
    # REGEX EXTRACTION: RESULT
    # ─────────────────────────────────────────────────────────
    def _extract_result(self, text: str, lines: list) -> str:
        """
        Returns normalised result string or None.
        Check in order of specificity (Distinction before Pass).
        """
        text_up = text.upper()

        result_map = [
            (r'\bI[-\s]?DIST\b|\bDISTINCTION\b|\bWITH\s+DISTINCTION\b', 'DISTINCTION'),
            (r'\bGRADE\s+I\b|\bFIRST\s+CLASS\b|\bFIRST\s+GRADE\b',       'FIRST CLASS'),
            (r'\bGRADE\s+II\b|\bSECOND\s+CLASS\b|\bSECOND\s+GRADE\b',    'SECOND CLASS'),
            (r'\bPASS\b',                                                   'PASS'),
            (r'\bFAIL\b|\bFAILED\b',                                       'FAIL'),
        ]

        for pattern, label in result_map:
            if re.search(pattern, text_up):
                return label

        return None

    # ─────────────────────────────────────────────────────────
    # UNIVERSITY FIELD EXTRACTORS
    # ─────────────────────────────────────────────────────────

    def _extract_numeric_field(self, text: str, lines: list, labels: list,
                                min_val: float, max_val: float,
                                prefer_last: bool = False, tight: bool = False):
        """
        Generic: find a decimal number near a label keyword.
        prefer_last=True returns the LAST match (for SPI → final semester).
        tight=True uses stricter regex to avoid misreads.
        Returns float or None.
        """
        label_re = re.compile('|'.join(re.escape(l) for l in labels), re.IGNORECASE)
        # Tighter regex for SPI (usually 1.00 to 10.00 with 2 decimal places)
        if tight:
            num_re = re.compile(r'\b([0-9][.,][0-9]{2,3})\b')
        else:
            num_re = re.compile(r'\b(\d{1,2}[.,]\d{1,4})\b')
            
        matches  = []

        # Strategy 1: same line
        for line in lines:
            lt = line['text']
            if label_re.search(lt):
                stripped = label_re.sub('', lt)
                for m in num_re.finditer(stripped):
                    try:
                        val = float(m.group(1).replace(',', '.'))
                        if min_val <= val <= max_val:
                            matches.append(round(val, 4))
                    except ValueError:
                        pass

        # Strategy 2: next line after label
        prev_was_label = False
        for line in lines:
            lt = line['text']
            if label_re.search(lt):
                prev_was_label = True
                continue
            if prev_was_label:
                for m in num_re.finditer(lt):
                    try:
                        val = float(m.group(1).replace(',', '.'))
                        if min_val <= val <= max_val:
                            matches.append(round(val, 4))
                    except ValueError:
                        pass
                prev_was_label = False

        # Strategy 3: regex in full text near label
        pattern = re.compile(
            '(' + '|'.join(re.escape(l) for l in labels) + r')[^\d]{0,40}(\d{1,2}[.,]\d{1,4})',
            re.IGNORECASE
        )
        for m in pattern.finditer(text):
            try:
                val = float(m.group(2).replace(',', '.'))
                if min_val <= val <= max_val:
                    matches.append(round(val, 4))
            except ValueError:
                pass

        if not matches:
            return None
        return matches[-1] if prefer_last else matches[0]

    def _extract_urn(self, text: str, lines: list):
        """
        Extract URN / Roll No / PRN / Enrollment number.
        Looks for a 6–12 digit number near a known label.
        """
        label_re = re.compile(
            r'\b(?:urn|university\s+roll|roll\s*no|enrollment|prn|'
            r'registration\s*no|seat\s*no|student\s*id|uid)\b',
            re.IGNORECASE
        )
        num_re = re.compile(r'\b(\d{6,12})\b')

        # Same line
        for line in lines:
            if label_re.search(line['text']):
                m = num_re.search(label_re.sub('', line['text']))
                if m:
                    return m.group(1)

        # Next line
        prev = False
        for line in lines:
            if label_re.search(line['text']):
                prev = True; continue
            if prev:
                m = num_re.search(line['text'])
                if m:
                    return m.group(1)
                prev = False

        # Full text scan
        m = re.search(
            r'(?:urn|roll\s*no|prn|enrollment)[^\d]{0,30}(\d{6,12})',
            text, re.IGNORECASE
        )
        if m:
            return m.group(1)

        return None

    def _extract_text_field(self, text: str, lines: list, labels: list,
                             min_len: int = 3, max_len: int = 100):
        """
        Extract a short text value following a label keyword.
        Used for Branch, Board/University, etc.
        Truncates at parentheses to avoid capturing full institute descriptions.
        """
        label_re = re.compile('|'.join(re.escape(l) for l in labels), re.IGNORECASE)
        noise_re = re.compile(
            r'^(?:of|the|in|and|for|a|an|to|is|by|with|from|at)$', re.IGNORECASE
        )

        def _trim(raw: str) -> str:
            """Trim garbage from extracted value."""
            # Stop at first parenthesis — e.g. 'Shivaji University (Kolhapur)' → 'Shivaji University'
            raw = re.sub(r'\s*\(.*', '', raw).strip()
            # Split at pipe/slash/dash separators — e.g. 'AI | Sem VII' → 'AI'
            parts = re.split(r'\s*[|/\\\u2013\u2014]\s*', raw)
            raw = parts[0].strip(' :.-')
            # Remove leading single-char + dashes: 'f——  AI and DS' → 'AI and DS'
            raw = re.sub(r'^[a-zA-Z]\s*[-=\u2013\u2014]{1,4}\s*', '', raw)
            return raw.strip()

        # Strategy 1: value on same line after the label
        for line in lines:
            lt = line['text']
            if label_re.search(lt):
                remainder = label_re.sub('', lt).strip(' :.-')
                val = _trim(remainder)
                if min_len <= len(val) <= max_len and not noise_re.match(val):
                    return val

        # Strategy 2: value on the next line
        prev = False
        for line in lines:
            if label_re.search(line['text']):
                prev = True
                continue
            if prev:
                val = _trim(line['text'].strip())
                if min_len <= len(val) <= max_len and not noise_re.match(val):
                    return val
                prev = False

        return None

    def _extract_year_field(self, text: str):
        """
        Extract academic year from the document.
        Priority:
          1. 'Examination: EVEN 2024-2025'  → '2024-2025'
          2. 'Academic Year: 2024-2025'      → '2024-2025'
          3. Year range '2022-23'            → '2022-2023'
          4. Standalone '2024'               → '2024'
        """
        # Priority 1 & 2: Academic year format YYYY-YYYY or YYYY-YY near keyword
        m = re.search(
            r'(?:year|batch|session|passing|exam|examination|academic)[^\d]{0,30}'
            r'((?:19|20)\d{2})[-\u2013](\d{2,4})',
            text, re.IGNORECASE
        )
        if m:
            y1 = m.group(1)
            y2 = m.group(2)
            if len(y2) == 2:
                y2 = y1[:2] + y2   # 24 → 2024
            return f"{y1}-{y2}"

        # Priority 3: Bare academic year range anywhere in text
        m = re.search(r'\b((?:19|20)\d{2})[-\u2013](\d{2,4})\b', text)
        if m:
            y1 = m.group(1)
            y2 = m.group(2)
            if len(y2) == 2:
                y2 = y1[:2] + y2
            return f"{y1}-{y2}"

        # Priority 4: Near a year keyword
        m = re.search(
            r'(?:year|batch|session|passing|exam)[^\d]{0,30}((?:19|20)\d{2})',
            text, re.IGNORECASE
        )
        if m:
            return m.group(1)

        # Priority 5: Any standalone 4-digit year 1990-2030
        years = re.findall(r'\b((?:19|20)\d{2})\b', text)
        valid = [y for y in years if 1990 <= int(y) <= 2030]
        if valid:
            return max(valid, key=int)

        return None
