from typing import List, Optional
from dataclasses import dataclass, field

@dataclass
class WordNode:
    id: int
    text: str
    x: int
    y: int
    w: int
    h: int
    conf: float
    center_x: int = field(init=False)
    center_y: int = field(init=False)
    
    def __post_init__(self):
        self.center_x = self.x + self.w // 2
        self.center_y = self.y + self.h // 2

@dataclass
class LineNode:
    id: int
    words: List[WordNode]
    text: str = field(init=False)
    y_center: float = field(init=False)
    x_min: int = field(init=False)
    x_max: int = field(init=False)
    
    def __post_init__(self):
        self.words.sort(key=lambda w: w.x)
        self.text = " ".join(w.text for w in self.words)
        self.y_center = sum(w.center_y for w in self.words) / len(self.words) if self.words else 0
        self.x_min = min(w.x for w in self.words) if self.words else 0
        self.x_max = max(w.x + w.w for w in self.words) if self.words else 0

class DocumentGraph:
    def __init__(self, words: List[WordNode]):
        self.words = words
        self.lines: List[LineNode] = []
    
    def build_lines(self):
        # Sort words by y-coordinate
        sorted_words = sorted(self.words, key=lambda w: w.center_y)
        lines = []
        current_line_words = []
        current_y = -1
        
        for w in sorted_words:
            if current_y == -1 or abs(w.center_y - current_y) < max(10, w.h * 0.5):
                current_line_words.append(w)
                current_y = sum(ww.center_y for ww in current_line_words) / len(current_line_words)
            else:
                if current_line_words:
                    lines.append(LineNode(id=len(lines), words=current_line_words))
                current_line_words = [w]
                current_y = w.center_y
                
        if current_line_words:
            lines.append(LineNode(id=len(lines), words=current_line_words))
            
        self.lines = sorted(lines, key=lambda l: l.y_center)
        
    def find_nearest_right(self, word: WordNode, max_dist_x=500, max_dist_y=20) -> Optional[WordNode]:
        candidates = [
            w for w in self.words
            if w.id != word.id and w.x > word.x + word.w and abs(w.center_y - word.center_y) < max_dist_y
        ]
        if candidates:
            return min(candidates, key=lambda w: w.x - (word.x + word.w))
        return None
        
    def find_nearest_below(self, word: WordNode, max_dist_x=50, max_dist_y=200) -> Optional[WordNode]:
        candidates = [
            w for w in self.words
            if w.id != word.id and w.center_y > word.center_y and abs(w.center_x - word.center_x) < max_dist_x
        ]
        if candidates:
            return min(candidates, key=lambda w: w.center_y - word.center_y)
        return None
