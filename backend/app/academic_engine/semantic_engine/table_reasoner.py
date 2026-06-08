class TableReasoner:
    """Step 8: Table Reasoning"""
    
    def extract_table_data(self, graph) -> dict:
        table_data = {
            "subjects": [],
            "total_marks": None,
            "obtained_marks": None
        }
        
        # Simple heuristic for table summary rows
        for node in graph.nodes:
            text_lower = node['text'].lower()
            if 'grand total' in text_lower or 'total marks' in text_lower:
                right_id = node['relationships']['nearest_right']
                if right_id:
                    table_data['total_marks'] = graph.get_node(right_id)['text']
                    
            if 'obtained' in text_lower and not 'marks' in text_lower:
                right_id = node['relationships']['nearest_right']
                if right_id:
                    table_data['obtained_marks'] = graph.get_node(right_id)['text']
                    
        return table_data
