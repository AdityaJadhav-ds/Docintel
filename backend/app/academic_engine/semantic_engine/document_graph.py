class DocumentGraph:
    """Step 2: Document Spatial Graph"""
    
    def __init__(self):
        self.nodes = []
        
    def build_graph(self, lines: list):
        self.nodes = []
        for line in lines:
            node = {
                "id": line['line_id'],
                "text": line['text'],
                "confidence": line['confidence'],
                "bbox": line['bbox'],
                "relationships": {
                    "nearest_right": None,
                    "nearest_left": None,
                    "nearest_below": None,
                    "aligned_with": []
                }
            }
            self.nodes.append(node)
            
        self._compute_relationships()
        return self
        
    def _compute_relationships(self):
        for i, nodeA in enumerate(self.nodes):
            xA, yA, wA, hA = nodeA['bbox']
            
            min_dist_right = float('inf')
            min_dist_below = float('inf')
            
            for j, nodeB in enumerate(self.nodes):
                if i == j:
                    continue
                    
                xB, yB, wB, hB = nodeB['bbox']
                
                # Right relationship (same row approx, B is right of A)
                if abs(yA - yB) < hA * 0.8 and xB >= xA:
                    dist = xB - (xA + wA)
                    if 0 <= dist < min_dist_right:
                        min_dist_right = dist
                        nodeA['relationships']['nearest_right'] = nodeB['id']
                        nodeB['relationships']['nearest_left'] = nodeA['id']
                        
                # Below relationship (B is below A, approx vertically aligned or nearby)
                if yB > yA and max(xA, xB) < min(xA + wA, xB + wB) + 100:
                    dist = yB - (yA + hA)
                    if 0 <= dist < min_dist_below:
                        min_dist_below = dist
                        nodeA['relationships']['nearest_below'] = nodeB['id']
                        
                # Alignment relationship (left aligned)
                if abs(xA - xB) < 15 and yB > yA:
                    nodeA['relationships']['aligned_with'].append(nodeB['id'])
                    
    def get_node(self, node_id):
        for n in self.nodes:
            if n['id'] == node_id:
                return n
        return None
