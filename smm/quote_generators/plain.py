import numpy as np
from typing import List, Tuple
from numba.types import Array

from frameworks.tools.numba import nbclip, nbgeomspace
from frameworks.tools.trading.rounding import round_ceil, round_floor
from frameworks.tools.trading.weights import generate_geometric_weights
from smm.quote_generators.base import QuoteGenerator
from smm.sharedstate import SmmSharedState


class PlainQuoteGenerator(QuoteGenerator):
    """
    This strategy uses an aggressiveness value to determine how powerful the price prediction 
    features are in influencing the quote's skew. 

    When closer to the midprice, the best bid/ask tends to be the most filled quotes
    and such their prices/sizes are very inflencial in resultant PnL. In this case, 
    """
    def __init__(self, ss: SmmSharedState) -> None:
        self.ss = ss
        super().__init__(self.ss)

    def corrected_skew(self, skew: float) -> float:
        """
        Calculate and return the skew value corrected for current inventory.

        Parameters
        ----------
        skew : float
            The original skew value.

        Returns
        -------
        float
            The corrected skew value.
        """
        corrective_amount = self.inventory_delta ** 2.0
        skew += corrective_amount if self.inventory_delta < 0.0 else -corrective_amount
        return skew

    def corrected_spread(self, spread: float) -> float:
        """
        Adjust the spread based on the minimum spread parameter.

        Parameters
        ----------
        spread : float
            The original spread value.

        Returns
        -------
        float
            The adjusted spread value.
        """
        min_spread = self.bps_to_decimal(self.params["minimum_spread"])
        if spread < min_spread:
            return min_spread
        else:
            return nbclip(spread, spread, min_spread * 5)
    
    def prepare_orders(self, bid_prices: Array, bid_sizes: Array, ask_prices: Array, ask_sizes: Array) -> List[Tuple]:
        """
        Prepare bid and ask orders based on given prices and sizes. 

        Ordering is done 1-bid-1-ask for greater priority to inner (closer to mid) orders 
        and decreasing priority going outward (away from mid). 

        Parameters
        ----------
        bid_prices : Array
            Array of bid prices.

        bid_sizes : Array
            Array of bid sizes.

        ask_prices : Array
            Array of ask prices.

        ask_sizes : Array
            Array of ask sizes.

        Returns
        -------
        List[Tuple]
            List of tuples representing bid and ask orders.
        """
        orders = []

        for (bid_price, bid_size, ask_price, ask_size) in zip(bid_prices, bid_sizes, ask_prices, ask_sizes):
            orders.append(self.generate_single_quote(
                side=0.0,
                orderType=0.0,
                price=round_floor(num=bid_price, step_size=self.tick_size),
                size=round_ceil(num=bid_size, step_size=self.lot_size) 
            ))

            orders.append(self.generate_single_quote(
                side=1.0,
                orderType=0.0,
                price=round_ceil(num=ask_price, step_size=self.tick_size),
                size=round_ceil(num=ask_size, step_size=self.lot_size)
            ))

        return orders
    
    def generate_positive_skew_quotes(self, skew: float, spread: float) -> List[Tuple]:
        """
        Generate positively skewed bid/ask quotes, with the intention to fill 
        more on the bid side (buy more) than the ask side (sell less). A larger strategy
        breakdown can be found in the README.md, or at the top of this class.
        
        Parameters
        ----------
        skew : float
            A value between -1 <-> 1 predicting the future price over some time horizon.
            
        spread : float
            A value in dollars of minimum price deviation over some time horizon.

        Returns
        -------
        List[Tuple]
            A list of single quotes.
        """
        half_spread = spread / 2
        aggressiveness = self.params["aggressiveness"] * (skew ** 0.5)

        best_bid_price = self.mid - (half_spread * (1.0 - aggressiveness))
        best_ask_price = best_bid_price + spread

        bid_prices = nbgeomspace(
            start=best_bid_price,
            end=best_bid_price - (spread ** 1.5),
            n=self.total_orders//2
        )

        ask_prices = nbgeomspace(
            start=best_ask_price,
            end=best_ask_price + (spread ** 1.5),
            n=self.total_orders//2
        )

        clipped_r = 0.5 + nbclip(skew, 0.0, 0.5)   # NOTE: Geometric ratio cant exceed 1.0

        bid_sizes = self.max_position * generate_geometric_weights(
            num=self.total_orders//2,
            r=clipped_r,
            reverse=True
        )
        
        ask_sizes = self.max_position * generate_geometric_weights(
            num=self.total_orders//2,
            r=0.5 + (clipped_r ** (2 + aggressiveness)),
            reverse=True
        )

        return self.prepare_orders(bid_prices, bid_sizes, ask_prices, ask_sizes)

    def generate_negative_skew_quotes(self, skew: float, spread: float) -> List:
        """
        Generate positively skewed bid/ask quotes, with the intention to fill 
        more on the bid side (buy more) than the ask side (sell less). A larger strategy
        breakdown can be found in the README.md, or at the top of this class.
        
        Parameters
        ----------
        skew : float
            A value between -1 <-> 1 predicting the future price over some time horizon.
            
        spread : float
            A value in dollars of minimum price deviation over some time horizon.

        Returns
        -------
        List[Tuple]
            A list of single quotes generated from self.generate_single_quote()
        """
        half_spread = spread / 2
        aggressiveness = self.params["aggressiveness"] * (skew ** 0.5)

        best_ask_price = self.mid + (half_spread * (1.0 - aggressiveness))
        best_bid_price = best_ask_price - spread

        bid_prices = nbgeomspace(
            start=best_bid_price,
            end=best_bid_price - (spread ** 1.5),
            n=self.total_orders//2
        )

        ask_prices = nbgeomspace(
            start=best_ask_price,
            end=best_ask_price + (spread ** 1.5),
            n=self.total_orders//2
        )

        clipped_r = 0.5 + nbclip(skew, 0.0, 0.5)   # NOTE: Geometric ratio cant exceed 1.0

        bid_sizes = self.max_position * generate_geometric_weights(
            num=self.total_orders//2,
            r=0.5 + (clipped_r ** (2 + aggressiveness)),
            reverse=True
        )
        
        ask_sizes = self.max_position * generate_geometric_weights(
            num=self.total_orders//2,
            r=clipped_r,
            reverse=True
        )

        return self.prepare_orders(bid_prices, bid_sizes, ask_prices, ask_sizes)

    def generate_quotes(self, skew: float, spread: float) -> List:
        if skew > 0.0:
            return self.generate_positive_skew_quotes(skew, spread)
        elif skew <= 0.0:
            return self.generate_negative_skew_quotes(skew, spread)