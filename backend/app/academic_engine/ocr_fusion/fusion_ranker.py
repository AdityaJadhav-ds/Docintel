class FusionRanker:
    """Groups overlapping bounding boxes from different OCR engines and preprocess variants."""
    
    def calculate_iou(self, boxA, boxB):
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
        yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        if interArea == 0:
            return 0.0

        boxAArea = boxA[2] * boxA[3]
        boxBArea = boxB[2] * boxB[3]
        
        iou = interArea / float(boxAArea + boxBArea - interArea)
        return iou

    def group_candidates(self, all_results: list, iou_threshold: float = 0.4) -> list:
        groups = []
        used = set()
        
        for i, res in enumerate(all_results):
            if i in used:
                continue
            
            group = [res]
            used.add(i)
            
            for j, other in enumerate(all_results):
                if j in used:
                    continue
                    
                if self.calculate_iou(res['bbox'], other['bbox']) > iou_threshold:
                    group.append(other)
                    used.add(j)
                    
            groups.append(group)
            
        # Sort groups roughly top-to-bottom, left-to-right to maintain reading order
        groups.sort(key=lambda g: (g[0]['bbox'][1] // 15, g[0]['bbox'][0]))
        return groups
