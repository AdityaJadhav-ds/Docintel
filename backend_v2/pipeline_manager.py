"""
pipeline_manager.py — Pipeline Execution Manager

Runs stages sequentially, captures failures gracefully, 
preserves partial outputs, and generates debug artifacts.
"""
import json
import logging
import traceback
import pathlib
import time

logger = logging.getLogger(__name__)

DEBUG_DIR = pathlib.Path("debug")
DEBUG_DIR.mkdir(exist_ok=True)

class PipelineManager:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.state = {
            "status": "success",
            "completed_stages": [],
            "error_stage": None,
            "error_message": "",
            "perf": {}
        }
        
    def save_debug(self, stage_name: str, data: any):
        try:
            path = DEBUG_DIR / f"{self.run_id}_{stage_name}.json"
            
            # Handle list of objects with to_dict
            if isinstance(data, list):
                dump_data = [d.to_dict() if hasattr(d, "to_dict") else d for d in data]
            # Handle single object with to_dict
            elif hasattr(data, "to_dict"):
                dump_data = data.to_dict()
            else:
                dump_data = data
                
            with open(path, "w") as f:
                json.dump(dump_data, f, default=str, indent=2)
        except Exception as e:
            logger.warning("Could not save debug for %s: %s", stage_name, e)

    def execute_stage(self, stage_name: str, func, *args, **kwargs):
        """
        Executes a pipeline stage safely.
        If it crashes, marks partial success and raises so the pipeline stops cleanly.
        """
        logger.info("[%s] Starting...", stage_name.upper())
        t = time.time()
        try:
            result = func(*args, **kwargs)
            ms = int((time.time() - t) * 1000)
            self.state["perf"][stage_name] = ms
            self.state["completed_stages"].append(stage_name)
            logger.info("[%s] done %dms", stage_name.upper(), ms)
            
            self.save_debug(stage_name, result)
            return result
            
        except Exception as exc:
            ms = int((time.time() - t) * 1000)
            logger.error("[%s] FAILED: %s\n%s", stage_name.upper(), exc, traceback.format_exc())
            
            self.state["status"] = "partial_success"
            self.state["error_stage"] = stage_name
            self.state["error_message"] = str(exc)
            self.state["perf"][stage_name] = ms
            
            # Raise internal exception to halt further stages, 
            # but allow the caller to catch and return partial data.
            raise PipelineStageError(stage_name, str(exc))

class PipelineStageError(Exception):
    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"Stage {stage} failed: {message}")
