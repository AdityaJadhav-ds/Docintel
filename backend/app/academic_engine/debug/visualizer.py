import os
import json
from typing import Dict, Any

class DebugVisualizer:
    def save(self, session_id: str, data: Dict[str, Any]):
        out_dir = f"academic_debug/{session_id}"
        os.makedirs(out_dir, exist_ok=True)
        
        with open(f"{out_dir}/extraction_graph.json", "w") as f:
            json.dump(data, f, indent=2)
