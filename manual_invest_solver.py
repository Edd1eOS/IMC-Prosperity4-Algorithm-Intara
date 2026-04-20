"""
IMC Prosperity 4 Round 2 Manual Challenge Solver: "Invest & Expand"

Finds the optimal allocation of 50,000 XIRECs across Research, Scale, Speed.

Model:
  PnL = Research(x) * Scale(y) * Speed_mult - (x + y + z) * 500

  Research(x) = 200,000 * ln(1+x) / ln(101)   [logarithmic, max 200,000]
  Scale(y)    = 7 * y / 100                     [linear, max 7.0]
  Speed_mult  = rank-based in [0.1, 0.9]       [depends on all players]
  Budget_Used = (x + y + z) * 500

  x, y, z: non-negative integers, x + y + z <= 100
"""

import numpy as np

LOG101 = np.log(101)
BUDGET = 50_000


# ======================================================================
#  Core functions
# ======================================================================

def R(x):
    """Research output for x% investment."""
    return 200_000 * np.log(1 + x) / LOG101 if x > 0 else 0.0


def S(y):
    """Scale output for y% investment."""
    return 7.0 * y / 100.0


def pnl(x, y, z, speed):
    """Net PnL for allocation (x, y, z) and speed multiplier."""
    return R(x) * S(y) * speed - (x + y + z) * 500


def best_xy(B):
    """Optimal integer (x, y) with x+y=B maximizing R(x)*S(y).

    Returns (x, y, product).
    """
    bx, bp = 0, -1.0
    for x in range(B + 1):
        p = R(x) * S(B - x)
        if p > bp:
            bp, bx = p, x
    return bx, B - bx, bp


def continuous_optimal_x(B):
    """Solve f'(x) = -ln(1+x) + (B-x)/(1+x) = 0 by bisection."""
    lo, hi = 0.0, float(B)
    for _ in range(200):
        mid = (lo + hi) / 2
        val = -np.log(1 + mid) + (B - mid) / (1 + mid)
        if val > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ======================================================================
#  Full analysis
# ======================================================================

def solve():
    W = 80
    print("=" * W)
    print("  IMC Prosperity 4 Round 2 | Manual Challenge: Invest & Expand")
    print("  Optimal Budget Allocation Solver")
    print("=" * W)

    print("""
  PnL = Research(x) * Scale(y) * Speed_mult - (x+y+z) * 500

    Research(x) = 200,000 * ln(1+x) / ln(101)   [log, saturates fast]
    Scale(y)    = 7 * y / 100                     [linear]
    Speed       = rank-based multiplier [0.1 .. 0.9]
    x + y + z <= 100  (integer percentages)
    """)

    # ==================================================================
    #  1. Optimal Research / Scale split
    # ==================================================================
    print("-" * W)
    print("  [1] OPTIMAL RESEARCH / SCALE SPLIT (at z=0, full budget to R+S)")
    print("-" * W)

    x_cont = continuous_optimal_x(100)
    xI, yI, prod0 = best_xy(100)

    print(f"\n  Continuous optimum: x = {x_cont:.2f}%  (Research)")
    print(f"  Integer optimum:   Research = {xI}%, Scale = {yI}%")
    print(f"  R({xI}) = {R(xI):,.2f}")
    print(f"  S({yI}) = {S(yI):.4f}")
    print(f"  R * S  = {prod0:,.2f}")
    print(f"\n  PnL at speed=0.5: {pnl(xI,yI,0,0.5):>12,.0f}")
    print(f"  PnL at speed=0.9: {pnl(xI,yI,0,0.9):>12,.0f}")
    print(f"  PnL at speed=0.1: {pnl(xI,yI,0,0.1):>12,.0f}")

    # Verify full-budget optimality
    print(f"\n  Full-budget optimality check (marginal value of 1% at worst speed=0.1):")
    marginal_y = R(xI) * (7.0 / 100.0) * 0.1
    print(f"    Marginal value of +1% Scale = {marginal_y:,.0f} vs cost 500 => {'USE' if marginal_y > 500 else 'SKIP'}")

    # ==================================================================
    #  2. Speed allocation trade-off table
    # ==================================================================
    print(f"\n{'-'*W}")
    print("  [2] SPEED ALLOCATION TRADE-OFF TABLE")
    print("-" * W)
    print(f"\n  {'z':>3}  {'R':>3}  {'S':>3}  {'R*S':>10}"
          f"  {'Net(s=.3)':>10}  {'Net(s=.5)':>10}  {'Net(s=.7)':>10}  {'Net(s=.9)':>10}")
    print("  " + "-" * 66)

    ztab = {}
    for z in range(51):
        x, y, prod = best_xy(100 - z)
        ztab[z] = (x, y, prod)
        if z <= 15 or z % 5 == 0:
            row = f"  {z:3d}  {x:3d}  {y:3d}  {prod:10,.0f}"
            for s in [0.3, 0.5, 0.7, 0.9]:
                row += f"  {pnl(x,y,z,s):10,.0f}"
            print(row)

    # ==================================================================
    #  3. Marginal cost of speed investment
    # ==================================================================
    print(f"\n{'-'*W}")
    print("  [3] MARGINAL COST OF EACH z% IN SPEED")
    print("-" * W)
    print(f"\n  {'z':>3}  {'R*S lost':>10}  {'%lost':>7}  "
          f"{'break-even: min speed needed':>30}")
    print("  " + "-" * 54)

    for z in range(1, 16):
        lost = prod0 - ztab[z][2]
        pct = lost / prod0 * 100
        # Break-even vs z=0 at s_old=0.5:
        #   ztab[z].prod * s_new > prod0 * 0.5
        #   s_new > prod0 / ztab[z].prod * 0.5
        ratio = prod0 / ztab[z][2]
        s_be = ratio * 0.5
        print(f"  {z:3d}  {lost:10,.0f}  {pct:6.2f}%  "
              f"  s > {s_be:.4f}  (vs z=0 at s=0.5)")

    # ==================================================================
    #  4. Global optimal by speed multiplier (brute force)
    # ==================================================================
    print(f"\n{'-'*W}")
    print("  [4] GLOBAL OPTIMAL ALLOCATION BY SPEED MULTIPLIER")
    print("-" * W)
    print(f"\n  (For fixed speed, z=0 is always optimal since z only adds cost.)")
    print(f"  (Real question: does investing z improve your rank enough?)\n")

    print(f"  {'Speed':>6}  {'R%':>4}  {'S%':>4}  {'Z%':>4}  {'Net PnL':>12}")
    print("  " + "-" * 36)
    for s10 in range(1, 10):
        s = s10 / 10.0
        # For fixed speed, z=0 is optimal
        x, y, prod = best_xy(100)
        p = pnl(x, y, 0, s)
        print(f"  {s:6.1f}  {x:4d}  {y:4d}  {0:4d}  {p:12,.0f}")

    # Also show: if z helps you reach that speed
    print(f"\n  Practical table: z investment -> required rank percentile to break even")
    print(f"  (Break even = same PnL as z=0 at speed=0.5, i.e. PnL = {pnl(xI,yI,0,0.5):,.0f})\n")
    ref_pnl = pnl(xI, yI, 0, 0.5)
    print(f"  {'z':>3}  {'R':>3}  {'S':>3}  {'min speed':>10}  {'rank percentile':>16}")
    print("  " + "-" * 40)
    for z in range(1, 16):
        x, y, prod = ztab[z]
        if prod > 0:
            s_need = (ref_pnl + (x + y + z) * 500) / prod
            # speed = 0.1 + percentile * 0.8
            pctile = (s_need - 0.1) / 0.8
            print(f"  {z:3d}  {x:3d}  {y:3d}  {s_need:10.4f}  {pctile:15.2%}")

    # ==================================================================
    #  5. Game theory analysis
    # ==================================================================
    print(f"\n{'-'*W}")
    print("  [5] GAME THEORY ANALYSIS FOR SPEED")
    print("-" * W)

    gap = prod0 * 0.8
    cost_z1 = prod0 - ztab[1][2]

    print(f"""
  Speed ranking mechanics:
    Rank 1 (highest z)  -> speed = 0.9
    Rank N (lowest z)   -> speed = 0.1
    Linear interpolation by rank; tied investments share same rank.
    Only submitted teams participate in ranking.

  Impact quantification (base R*S = {prod0:,.0f}):
    Speed 0.1 -> 0.9:  +{gap:,.0f} PnL  ({gap/BUDGET:.0f}x entire budget!)
    Speed 0.1 -> 0.5:  +{prod0*0.4:,.0f} PnL
    Speed 0.5 -> 0.9:  +{prod0*0.4:,.0f} PnL

  Cost of z=1%:
    R*S product lost: {cost_z1:,.0f}  ({cost_z1/prod0*100:.2f}% of base)
    Budget cost: 500 XIRECs (negligible)
    Total cost at speed=0.5: ~{cost_z1*0.5 + 500:,.0f} PnL

  Benefit of z=1%:
    Beats ALL z=0 players in rank
    If >50% of teams invest z=0, you get speed > 0.5

  Strategic assessment:
    - Speed is zero-sum: redistributes PnL, doesn't create it
    - Range is 9x (0.1 to 0.9), making rank EXTREMELY high-value
    - Each z% costs ~{cost_z1/prod0*100:.1f}% of R*S product (tiny)
    - Rational equilibrium: small z=2~5 to beat the z=0 majority
    - Over-investing (z>15) wastes budget with diminishing rank benefit

  Expected population behavior (large player pool):
    ~40%  invest z=0   (naive or pure-math optimizers)
    ~25%  invest z=1-5  (analytically aware)
    ~20%  invest z=5-15  (strategically aggressive)
    ~15%  invest z=15+   (over-investing)
    """)

    # ==================================================================
    #  6. Scenario comparison
    # ==================================================================
    print("-" * W)
    print("  [6] SCENARIO COMPARISON")
    print("-" * W)

    # Show PnL matrix for z=0..10 at different achieved percentiles
    print(f"\n  PnL by allocation vs achieved speed percentile:")
    print(f"       (percentile = fraction of players you beat in speed)\n")

    header = f"  {'z':>3}  {'R':>3}  {'S':>3}"
    pctiles = [0.00, 0.25, 0.50, 0.75, 1.00]
    for p in pctiles:
        s = 0.1 + p * 0.8
        header += f"  {'p='+f'{p:.0%}'+'(s='+f'{s:.1f}'+')':>16}"
    print(header)
    print("  " + "-" * (18 + 16 * len(pctiles)))

    for z in range(11):
        x, y, _ = ztab[z]
        row = f"  {z:3d}  {x:3d}  {y:3d}"
        for p in pctiles:
            s = 0.1 + p * 0.8
            row += f"  {pnl(x,y,z,s):16,.0f}"
        print(row)

    # ==================================================================
    #  7. Final recommendations
    # ==================================================================
    print(f"\n{'='*W}")
    print("  [7] FINAL RECOMMENDATIONS")
    print(f"{'='*W}")

    recs = [
        ("CONSERVATIVE", 0, 0.50,
         "Maximize R*S, accept median speed."),
        ("SLIGHT EDGE", 2, 0.60,
         "Beats z=0 and z=1 players at negligible cost."),
        ("RECOMMENDED", 5, 0.70,
         "High likelihood of top-half speed at small R*S cost."),
        ("AGGRESSIVE", 10, 0.80,
         "Near-certain top speed rank, moderate R*S sacrifice."),
    ]

    for label, z, spd, desc in recs:
        x, y, prod = ztab[z]
        p = pnl(x, y, z, spd)
        lo = pnl(x, y, z, 0.1)
        hi = pnl(x, y, z, 0.9)
        print(f"\n  [{label}]")
        print(f"  Research={x}%  Scale={y}%  Speed={z}%")
        print(f"  {desc}")
        print(f"  Expected PnL (s={spd}): {p:>10,.0f}")
        print(f"  PnL range: {lo:>10,.0f} (worst) .. {hi:>10,.0f} (best)")

    # Top pick
    z_pick = 5
    xp, yp, _ = ztab[z_pick]
    print(f"\n{'='*W}")
    print(f"  >>> SUGGESTED SUBMISSION: Research={xp}%  Scale={yp}%  Speed={z_pick}% <<<")
    print(f"      PnL at speed 0.7: {pnl(xp,yp,z_pick,0.7):>10,.0f}")
    print(f"      PnL at speed 0.5: {pnl(xp,yp,z_pick,0.5):>10,.0f}")
    print(f"      PnL at speed 0.3: {pnl(xp,yp,z_pick,0.3):>10,.0f}")
    print(f"{'='*W}")


if __name__ == "__main__":
    solve()
