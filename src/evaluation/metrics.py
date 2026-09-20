from typing import List, Dict, Any
import numpy as np
from sklearn.metrics import cohen_kappa_score, mean_squared_error

class AssessmentMetrics:
    """
    Evaluation metrics calculating Inter-Rater Reliability (Cohen's Kappa),
    Mean Absolute Deviation, and Quadratic Weighted Kappa (QWK)
    against human ground-truth evaluations.
    """
    @staticmethod
    def calculate_agreement(human_scores: List[float], model_scores: List[float]) -> Dict[str, float]:
        y_true = np.array(human_scores)
        y_pred = np.array(model_scores)
        
        mse = float(mean_squared_error(y_true, y_pred))
        mae = float(np.mean(np.abs(y_true - y_pred)))
        correlation = float(np.corrcoef(y_true, y_pred)[0, 1]) if len(y_true) > 1 else 1.0

        # Discretize for Quadratic Weighted Kappa proxy
        bins = np.linspace(min(y_true), max(y_true) + 1e-5, num=5)
        cat_true = np.digitize(y_true, bins)
        cat_pred = np.digitize(y_pred, bins)
        kappa = float(cohen_kappa_score(cat_true, cat_pred, weights="quadratic"))

        return {
            "mean_squared_error": round(mse, 4),
            "mean_absolute_error": round(mae, 4),
            "pearson_correlation": round(correlation, 4),
            "quadratic_weighted_kappa": round(kappa, 4)
        }
