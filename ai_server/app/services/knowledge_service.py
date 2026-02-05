import google.generativeai as genai
from app.core.config import settings
import logging
from typing import List, Optional
import json
import asyncio
from app.schemas.knowledge import (
    RawFeedbackItem,
    KnowledgeCandidate,
    RefineCandidatesResponseData,
    EvaluateCandidateInput,
    EvaluateSimilarInput,
    KnowledgeEvaluationResult,
    BatchKnowledgeEvaluationResult,
    KnowledgeAction,
)
from app.services.embedding_service import embedding_service
from app.core.prompts import KNOWLEDGE_REFINEMENT_PROMPT, KNOWLEDGE_EVALUATION_PROMPT

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self):
        # Production code should rely on standard Config initialization.
        # Test scripts must ensure environment is set up before importing/initializing.
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            # 1. Refinement용 Flash 모델 (단순 정제, 속도/비용 중시)
            self.flash_model = genai.GenerativeModel("gemini-3-flash-preview")
            # 2. Evaluation용 Pro 모델 (논리적 추론, 정확도 중시)
            self.pro_model = genai.GenerativeModel("gemini-3-pro-preview")
        else:
            logger.warning(
                "GEMINI_API_KEY not found. KnowledgeService may not function correctly."
            )

    async def refine_candidates_batch(
        self, items: List[RawFeedbackItem]
    ) -> RefineCandidatesResponseData:
        """
        Refines raw feedback into formal knowledge candidates and generates embeddings.
        Returns wrapped response data.
        """

        # Parallel execution for refinement
        async def process_item(item: RawFeedbackItem) -> Optional[KnowledgeCandidate]:
            try:
                # 1. Refine Text
                prompt = KNOWLEDGE_REFINEMENT_PROMPT.format(
                    keyword=item.keyword, raw_feedback=item.rawFeedback
                )
                response = await self.flash_model.generate_content_async(prompt)
                refined_text = response.text.strip()

                # 2. Vectorize
                # Using is_query=False (Document)
                embedding = embedding_service.generate_embedding(
                    refined_text, is_query=False
                )

                return KnowledgeCandidate(
                    id=item.id,
                    keyword=item.keyword,
                    refinedText=refined_text,
                    embedding=embedding,
                )
            except Exception as e:
                logger.error(f"Failed to refine item {item.id}: {e}")
                return None

        # Execute parallel
        tasks = [process_item(item) for item in items]
        processed_results = await asyncio.gather(*tasks)

        # Filter None
        candidates = [r for r in processed_results if r is not None]

        return RefineCandidatesResponseData(
            processedCount=len(candidates), candidates=candidates
        )

    async def evaluate_knowledge(
        self, candidate: EvaluateCandidateInput, similars: List[EvaluateSimilarInput]
    ) -> BatchKnowledgeEvaluationResult:
        """
        Evaluates a candidate against existing similar knowledge entries.
        Returns multiple decisions, one for each similar item.
        """
        try:
            # Formulate Prompt with keyword context
            similars_text_list = []
            for s in similars:
                similars_text_list.append(
                    f"- ID: {s.id} (Keyword: {s.keyword}, Similarity: {s.similarity:.4f})\n  Content: {s.text}"
                )

            similars_text = "\n".join(similars_text_list)
            if not similars_text:
                similars_text = "(No similar knowledge found)"

            # Re-check: earlier I used REFINEMENT for EVALUATION?
            # No, let's fix. Code below uses correct EVALUATION prompt.
            prompt = KNOWLEDGE_EVALUATION_PROMPT.format(
                candidate=candidate.text, similars=similars_text
            )

            response = await self.pro_model.generate_content_async(prompt)

            # Parse JSON
            cleaned_text = (
                response.text.replace("```json", "").replace("```", "").strip()
            )
            try:
                data = json.loads(cleaned_text)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from Gemini: {cleaned_text}")
                raise ValueError("INVALID_LLM_RESPONSE")

            # Process results array
            results_data = data.get("results", [])
            if not results_data:
                logger.warning("No results in LLM response, returning empty batch")
                return BatchKnowledgeEvaluationResult(results=[])

            processed_results = []
            for result_item in results_data:
                # Validate decision
                decision_str = result_item.get("decision", "IGNORE")
                try:
                    decision = KnowledgeAction(decision_str)
                except ValueError:
                    logger.warning(
                        f"Invalid decision '{decision_str}', defaulting to IGNORE"
                    )
                    decision = KnowledgeAction.IGNORE

                # Generate vector for UPDATE decisions
                final_vector = None
                final_content = result_item.get("finalContent")
                if decision == KnowledgeAction.UPDATE and final_content:
                    final_vector = embedding_service.generate_embedding(
                        final_content, is_query=False
                    )

                processed_results.append(
                    KnowledgeEvaluationResult(
                        decision=decision,
                        targetId=str(result_item.get("targetId"))
                        if result_item.get("targetId") is not None
                        else None,
                        finalContent=final_content,
                        finalVector=final_vector,
                        reasoning=result_item.get("reasoning", ""),
                    )
                )

            return BatchKnowledgeEvaluationResult(results=processed_results)

        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            raise e


knowledge_service = KnowledgeService()
