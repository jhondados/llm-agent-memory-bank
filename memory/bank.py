"""LLM Agent Memory Bank with 4 memory types."""
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from datetime import datetime
from typing import List, Dict, Optional
import uuid, json

class AgentMemoryBank:
    def __init__(self, url: str = "http://localhost:6333"):
        self.qdrant = QdrantClient(url=url)
        self.encoder = SentenceTransformer("all-MiniLM-L6-v2")
        self._init_collections()

    def _init_collections(self):
        for name in ["episodic", "semantic", "procedural"]:
            try: self.qdrant.create_collection(name, vectors_config=VectorParams(size=384, distance=Distance.COSINE))
            except: pass

    def remember(self, content: str, memory_type: str = "episodic", metadata: Dict = None):
        embedding = self.encoder.encode(content).tolist()
        point = PointStruct(id=str(uuid.uuid4()), vector=embedding,
            payload={"content": content, "timestamp": datetime.now().isoformat(),
                     "access_count": 0, **(metadata or {})})
        self.qdrant.upsert(collection_name=memory_type, points=[point])

    def recall(self, query: str, memory_type: str = "episodic", top_k: int = 5,
               min_score: float = 0.7) -> List[Dict]:
        embedding = self.encoder.encode(query).tolist()
        results = self.qdrant.search(collection_name=memory_type, query_vector=embedding, limit=top_k, score_threshold=min_score)
        memories = [{"content": r.payload["content"], "score": r.score,
                     "timestamp": r.payload.get("timestamp"), "id": r.id} for r in results]
        # Update access counts for retrieved memories
        for r in results:
            self.qdrant.set_payload(collection_name=memory_type, payload={"access_count": r.payload.get("access_count", 0) + 1}, points=[r.id])
        return memories

    def consolidate(self, threshold: float = 0.95):
        """Remove near-duplicate memories (consolidation/sleep phase)."""
        all_pts = self.qdrant.scroll("episodic", limit=1000)[0]
        if len(all_pts) < 10: return
        embeddings = [p.vector for p in all_pts if p.vector]
        # Simple greedy deduplication
        kept = [all_pts[0].id]
        for i, pt in enumerate(all_pts[1:], 1):
            if pt.vector:
                from scipy.spatial.distance import cosine
                max_sim = max(1 - cosine(pt.vector, all_pts[j].vector) for j in range(i) if all_pts[j].id in kept)
                if max_sim < threshold: kept.append(pt.id)
        removed = len(all_pts) - len(kept)
        print(f"Consolidation: kept {len(kept)}, removed {removed} near-duplicates")
