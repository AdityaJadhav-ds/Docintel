import cv2
import numpy as np
from typing import List, Dict, Any
from ..models import OCRToken

class TableParser:
    def detect_tables(self, img_binary: np.ndarray, tokens: List[OCRToken]) -> List[Dict[str, Any]]:
        scale = 15
        
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (img_binary.shape[1] // scale, 1))
        horizontal_lines = cv2.morphologyEx(img_binary, cv2.MORPH_OPEN, horizontal_kernel)
        
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, img_binary.shape[0] // scale))
        vertical_lines = cv2.morphologyEx(img_binary, cv2.MORPH_OPEN, vertical_kernel)
        
        # Find individual cells by taking RETR_TREE or intersecting lines
        table_mask = cv2.bitwise_and(horizontal_lines, vertical_lines)
        # Dilate intersection points
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        joints = cv2.dilate(table_mask, kernel, iterations=2)
        
        # We actually need cells, so let's find contours of the grid itself
        grid = cv2.addWeighted(horizontal_lines, 0.5, vertical_lines, 0.5, 0.0)
        _, grid = cv2.threshold(grid, 50, 255, cv2.THRESH_BINARY)
        
        # Invert grid to find empty cells as contours
        inv_grid = cv2.bitwise_not(grid)
        contours, hierarchy = cv2.findContours(inv_grid, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        
        cells = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            # Filter valid cells
            if 20 < w < img_binary.shape[1]*0.9 and 10 < h < img_binary.shape[0]*0.9:
                cells.append({"x": x, "y": y, "w": w, "h": h})
                
        # Group cells into rows by Y proximity
        cells.sort(key=lambda c: (c['y'], c['x']))
        rows = []
        current_row = []
        last_y = -1
        
        for cell in cells:
            if last_y == -1 or abs(cell['y'] - last_y) < 15:
                current_row.append(cell)
            else:
                if current_row:
                    current_row.sort(key=lambda c: c['x'])
                    rows.append(current_row)
                current_row = [cell]
            last_y = cell['y']
            
        if current_row:
            current_row.sort(key=lambda c: c['x'])
            rows.append(current_row)
            
        # Map tokens into cells
        for r in rows:
            for c in r:
                c['text'] = " ".join([t.text for t in tokens if t.x1 >= c['x'] and t.x2 <= c['x']+c['w'] and t.y1 >= c['y'] and t.y2 <= c['y']+c['h']])
                
        # Filter empty rows
        filtered_rows = [[c for c in r if c['text'].strip()] for r in rows]
        filtered_rows = [r for r in filtered_rows if len(r) > 1] # at least 2 cells per row
        
        tables = []
        if filtered_rows:
            tables.append({
                "rows": len(filtered_rows),
                "cells": sum(len(r) for r in filtered_rows),
                "type": "data_table",
                "strategy": "opencv_morphology_cell_segmentation",
                "data": [[c['text'] for c in r] for r in filtered_rows]
            })
        
        return tables
