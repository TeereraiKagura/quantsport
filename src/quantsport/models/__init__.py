from quantsport.models.base import BaseRate, Forecast, Model
from quantsport.models.bayesian import BayesianStrengths
from quantsport.models.dixon_coles import DixonColes
from quantsport.models.logistic import LogisticMarkets
from quantsport.models.poisson import PoissonRegression


def default_models() -> list[Model]:
    """One fresh instance of every Phase 2 model, plus the base-rate benchmark."""
    return [BaseRate(), PoissonRegression(), DixonColes(), BayesianStrengths(), LogisticMarkets()]


__all__ = [
    "BaseRate", "BayesianStrengths", "DixonColes", "Forecast", "LogisticMarkets",
    "Model", "PoissonRegression", "default_models",
]
