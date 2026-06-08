from typing import List
from .relationship_graph import DocumentGraph, LineNode

class BlockNode:
    def __init__(self, lines: List[LineNode]):
        self.lines = lines
        self.text = "\n".join(l.text for l in self.lines)
        self.y_min = min(l.y_center for l in self.lines)
        self.y_max = max(l.y_center for l in self.lines)

def build_blocks(graph: DocumentGraph) -> List[BlockNode]:
    """Group lines into logical vertical blocks (e.g. paragraphs, tables)."""
    if not graph.lines:
        return []
        
    blocks = []
    current_block_lines = []
    last_y = -1
    
    for line in graph.lines:
        if last_y == -1 or (line.y_center - last_y) < 50:  # 50px vertical gap heuristic
            current_block_lines.append(line)
        else:
            if current_block_lines:
                blocks.append(BlockNode(current_block_lines))
            current_block_lines = [line]
        last_y = line.y_center
        
    if current_block_lines:
        blocks.append(BlockNode(current_block_lines))
        
    return blocks
