from .field_validator import FieldValidator
from .consistency_checker import ConsistencyChecker
from .hallucination_detector import HallucinationDetector
from .numeric_repair import NumericRepair
from .semantic_sanity import SemanticSanity
from .retry_manager import RetryManager
from .confidence_recalibrator import ConfidenceRecalibrator
from .debug_validator import DebugValidator

class HealingPipeline:
    """Step 9: Self-Healing Pipeline Orchestrator"""
    
    def __init__(self):
        self.validator = FieldValidator()
        self.consistency = ConsistencyChecker()
        self.hallucination = HallucinationDetector()
        self.repair = NumericRepair()
        self.sanity = SemanticSanity()
        self.retry_manager = RetryManager()
        self.recalibrator = ConfidenceRecalibrator()
        self.explainer = DebugValidator()
        
    def process(self, extracted_fields: dict, full_document_text: str, image_crops: dict, ocr_callable) -> dict:
        healed_fields = {}
        warnings = []
        
        for field_name, field_data in extracted_fields.items():
            value = field_data['value']
            conf = field_data['confidence']
            is_valid = True
            error_msg = ""
            was_repaired = False
            retries = 0
            
            # 1. Hallucination Check
            is_hal, msg = self.hallucination.is_hallucination(field_name, value, conf)
            if is_hal:
                is_valid = False
                error_msg = msg
                warnings.append(f"Hallucination detected in {field_name}: {msg}")
            
            # 2. Repair Engine
            if is_valid and field_name in ['percentage', 'cgpa', 'spi', 'total_marks', 'obtained_marks']:
                value, was_repaired = self.repair.repair(value, field_name)
                
            # 3. Field Specific Validation
            if is_valid:
                if field_name == 'name':
                    is_valid, error_msg = self.validator.validate_name(value, conf)
                elif field_name == 'percentage':
                    is_valid, error_msg = self.validator.validate_percentage(value)
                elif field_name == 'cgpa' or field_name == 'spi':
                    is_valid, error_msg = self.validator.validate_cgpa(value)
                elif field_name == 'year':
                    is_valid, error_msg = self.validator.validate_year(value)
                elif field_name == 'result':
                    is_valid, error_msg = self.validator.validate_result(value)
                elif field_name in ('obtained_marks', 'total_marks'):
                    is_valid, error_msg = self.validator.validate_marks(value)
                    
            if not is_valid:
                warnings.append(f"Validation failed for {field_name}: {error_msg}")
                
            # 4. Retry Logic
            if not is_valid or conf < 0.5:
                crop = image_crops.get(field_name)
                if crop is not None:
                    retry_res = self.retry_manager.execute_retry(field_data, crop, ocr_callable)
                    if retry_res and retry_res['value'] != value:
                        # Re-evaluate repaired value
                        value = retry_res['value']
                        retries = retry_res['retries_used']
                        # Re-evaluate validity after retry
                        is_valid = True
                        if field_name == 'name':
                            is_valid, _ = self.validator.validate_name(value, retry_res.get('confidence', conf))
                        elif field_name == 'percentage':
                            is_valid, _ = self.validator.validate_percentage(value)
                        elif field_name in ['cgpa', 'spi']:
                            is_valid, _ = self.validator.validate_cgpa(value)
                        elif field_name == 'year':
                            is_valid, _ = self.validator.validate_year(value)
                        elif field_name == 'result':
                            is_valid, _ = self.validator.validate_result(value)
                        
            # 5. Recalibrate Confidence
            final_conf = self.recalibrator.recalibrate(conf, was_repaired, is_valid, retries)
            
            # STEP 1: HARD REJECTION SYSTEM
            # If not validated or hallucination == true, DO NOT send original value.
            if not is_valid or is_hal:
                value = None
                is_valid = False
            
            # Log for Debug
            self.explainer.log_field(field_name, field_data['value'], error_msg, retries, value, final_conf)
            
            # 6. Step 11: Final Response Format
            # Preserve original OCR raw value for the sanitizer's rejected_fields log
            healed_fields[field_name] = {
                "value": value,
                "original_ocr_value": field_data['value'],  # raw before nullification
                "confidence": final_conf,
                "validated": is_valid,
                "repaired": was_repaired,
                "retries_used": retries,
                "extraction_strategy": "healed" if retries > 0 else field_data.get('extraction_strategy', 'initial')
            }
            
        # STEP 4: MATHEMATICAL RECOVERY
        if 'obtained_marks' in healed_fields and 'total_marks' in healed_fields:
            obt_val = healed_fields['obtained_marks']['value']
            tot_val = healed_fields['total_marks']['value']
            
            if obt_val is not None and tot_val is not None:
                try:
                    obt = float(obt_val)
                    tot = float(tot_val)
                    if tot > 0 and obt <= tot:
                        recovered_pct = round((obt / tot) * 100, 2)
                        
                        if 'percentage' not in healed_fields:
                            healed_fields['percentage'] = {
                                "value": None, "confidence": 0.0, "validated": False, 
                                "repaired": False, "retries_used": 0, "extraction_strategy": "initial"
                            }
                        
                        # Override percentage if it was missing or invalid or if the recovered one is more reliable
                        if healed_fields['percentage']['value'] is None or not healed_fields['percentage']['validated']:
                            healed_fields['percentage']['value'] = recovered_pct
                            healed_fields['percentage']['confidence'] = 0.99
                            healed_fields['percentage']['validated'] = True
                            healed_fields['percentage']['extraction_strategy'] = 'mathematical_recovery'
                            healed_fields['percentage']['repaired'] = True
                except (ValueError, TypeError):
                    pass

        # Global Consistency and Sanity Checks
        inconsistencies = self.consistency.check_consistency(healed_fields)
        if inconsistencies:
            warnings.extend(inconsistencies)
            
        sanity_warnings = self.sanity.check_sanity(healed_fields, full_document_text)
        if sanity_warnings:
            warnings.extend(sanity_warnings)
            
        return {
            "healed_fields": healed_fields,
            "warnings": warnings, # NEVER silently fail
            "debug_logs": self.explainer.get_logs()
        }
