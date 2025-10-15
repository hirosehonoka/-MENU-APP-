#ログから取得したAPI出力コード・ソルバー用  ※ログからAPIを通すために22秒かかっている
import pyomo.environ as pyo
from pyomo.opt import SolverFactory

def build_model(
    Days,                # list of 7 days
    Recipes,             # dict recipeId -> dict with keys: 'kind1', 'kind2', 'recipeTitle'
    RecipeItem,          # dict of (recipeId, itemName) -> amount
    RecipeNutrition,     # dict of recipeId -> dict of nutritionName -> value (per recipe)
    NutritionalTarget,   # dict with keys: 'nutritionals' (dict of nutrient name -> value), 'userInfo' for matching
    userInfo,            # dict of user information including userInfo attributes for matching NutritionalTarget
    ItemWeight,          # dict of itemName -> weights (list of multiples allowed)
    ItemEqual            # dict of itemName -> equals (list of equivalent itemName)
):
    model = pyo.ConcreteModel()

    model.Days = pyo.Set(initialize=Days)
    model.Recipes = pyo.Set(initialize=list(Recipes.keys()))
    model.Nutrients = set()
    for rec_id in Recipes:
        model.Nutrients.update(RecipeNutrition[rec_id].keys())
    model.Nutrients = list(model.Nutrients)

    # Identify item equivalences: build map from each itemName to a canonical name
    def canonical_item(item):
        # Flatten equivalences
        checked = set()
        stack = [item]
        while stack:
            curr = stack.pop()
            if curr in checked:
                continue
            checked.add(curr)
            if curr in ItemEqual:
                for eq in ItemEqual[curr]['equals']:
                    if eq not in checked:
                        stack.append(eq)
        return min(checked)
    # Actually unify equivalences by minimal itemName in equivalence class
    # Build equivalence classes
    eq_classes = []
    processed_items = set()
    for item in ItemEqual:
        if item in processed_items:
            continue
        group = set()
        stack = [item]
        while stack:
            it = stack.pop()
            if it in group:
                continue
            group.add(it)
            if it in ItemEqual:
                stack.extend(ItemEqual[it]['equals'])
        eq_classes.append(group)
        processed_items |= group
    # Create map itemName -> canonical
    canonical_map = {}
    for group in eq_classes:
        representative = min(group)
        for it in group:
            canonical_map[it] = representative
    # Items not in any equivalence group map to themselves
    all_items = set()
    for ri in RecipeItem:
        all_items.add(ri[1])
    for it in all_items:
        if it not in canonical_map:
            canonical_map[it] = it

    # Create sets of recipes by kind1 and kind2 (for main classifications)
    kind1_map = {}
    kind2_map = {}
    for rid in Recipes:
        k1 = Recipes[rid].get('kind1', None)
        k2 = Recipes[rid].get('kind2', None)
        if k1 not in kind1_map:
            kind1_map[k1] = []
        kind1_map[k1].append(rid)
        if k2 not in kind2_map:
            kind2_map[k2] = []
        kind2_map[k2].append(rid)

    # Classify recipes by meal kind for assignment (主食 staple, 主菜 main, 副菜 side, 汁物 soup)
    # Assuming these keys exist in kind1 or kind2 to identify
    # We will define sets:
    model.StapleRecipes = pyo.Set(initialize=kind1_map.get('staple', []))
    model.MainRecipes = pyo.Set(initialize=kind1_map.get('main', []))
    model.SideRecipes = pyo.Set(initialize=kind1_map.get('side', []))
    model.SoupRecipes = pyo.Set(initialize=kind1_map.get('soup', []))
    # "ご飯もの" or "パスタ" is identified in kind2 (e.g. 'gohanmono', 'pasta')
    gohan_pasta_kinds = set(['ご飯もの', 'パスタ'])
    gohan_pasta_recipes = []
    for k2 in gohan_pasta_kinds:
        gohan_pasta_recipes.extend(kind2_map.get(k2, []))
    model.GohanPastaRecipes = pyo.Set(initialize=gohan_pasta_recipes)

    # Identify nutritional target via userInfo matching without using targetId as key
    matched_target = None
    for nt in NutritionalTarget:
        # Assume userInfo means matching keys & values identical in dict
        matches = True
        for k,v in userInfo.items():
            if k not in NutritionalTarget[nt]['userInfo'] or NutritionalTarget[nt]['userInfo'][k] != v:
                matches = False
                break
        if matches:
            matched_target = NutritionalTarget[nt]
            break
    if matched_target is None:
        # no matching target, model infeasible
        model.Infeasible = pyo.Constraint(expr=pyo.Constraint.Infeasible)
        return model

    nutri_target = matched_target['nutritionals']

    # Process nutritional limits and conversions
    # fix protein, lipid, carbohydrate limits from the description
    # cal = calorie base
    cal_value = nutri_target.get('カロリー', None)
    # Build dictionaries for upper and lower limits of nutrients after conversions
    upper_limits = {}
    lower_limits = {}
    exact_limits = {}
    for nut_name, val in nutri_target.items():
        # Skip userInfo attribute etc
        if not isinstance(val, (int,float)): continue
        if nut_name.endswith('_上限'):
            base_name = nut_name[:-3]
            if base_name in ['たんぱく質', '脂質', '炭水化物'] and cal_value is not None:
                if base_name == 'たんぱく質':
                    upper_limits[base_name] = cal_value * val / 400
                elif base_name == '脂質':
                    upper_limits[base_name] = cal_value * val / 900
                elif base_name == '炭水化物':
                    upper_limits[base_name] = cal_value * val / 400
            else:
                upper_limits[base_name] = val
        elif nut_name.endswith('_下限'):
            base_name = nut_name[:-3]
            if base_name in ['たんぱく質', '脂質', '炭水化物'] and cal_value is not None:
                if base_name == 'たんぱく質':
                    lower_limits[base_name] = cal_value * val / 400
                elif base_name == '脂質':
                    lower_limits[base_name] = cal_value * val / 900
                elif base_name == '炭水化物':
                    lower_limits[base_name] = cal_value * val / 400
            else:
                lower_limits[base_name] = val
        else:
            # If nutrient is calorie, exact limits ±10%
            if nut_name == 'カロリー' and cal_value is not None:
                exact_limits[nut_name] = val
            else:
                # Lower bound only
                lower_limits[nut_name] = val

    # Decision variables: binary selection variables for each day and recipe and meal kind
    model.staple = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.main = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.side = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.soup = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)

    # Quantity variables: continuous amount of each recipe per day 
    # But actual amount must respect ItemWeight multiples only for certain items
    model.amount = pyo.Var(model.Days, model.Recipes, domain=pyo.NonNegativeReals)

    # Helper: check if recipe is gohan or pasta
    def is_gohan_or_pasta(rid):
        return rid in model.GohanPastaRecipes

    # Constraint: Each day must have one main dish, one soup, one side and one staple
    def c_main_once_day(model,d):
        return sum(model.main[d,r] for r in model.MainRecipes) == 1
    model.MainOnce = pyo.Constraint(model.Days, rule=c_main_once_day)

    def c_soup_once_day(model,d):
        return sum(model.soup[d,r] for r in model.SoupRecipes) == 1
    model.SoupOnce = pyo.Constraint(model.Days, rule=c_soup_once_day)

    def c_side_once_day(model,d):
        # If staple is gohan/pasta, side is omitted (only 3 dishes)
        supp_staple = sum(model.staple[d,r] for r in model.GohanPastaRecipes)
        if supp_staple == 1:
            return sum(model.side[d,r] for r in model.SideRecipes) == 0
        else:
            return sum(model.side[d,r] for r in model.SideRecipes) == 1
    def side_once_day_rule(model,d):
        gohan_pasta_selected = [r for r in model.GohanPastaRecipes if (d,r) in model.staple.index_set()]
        count = sum(model.staple[d,r] for r in model.GohanPastaRecipes)
        # Use constraint trick: side == 1 - gohan_pasta_selected
        return sum(model.side[d,r] for r in model.SideRecipes) == 1 - count
    model.SideOnce = pyo.Constraint(model.Days, rule=side_once_day_rule)

    def c_staple_once_day(model,d):
        return sum(model.staple[d,r] for r in model.StapleRecipes) == 1
    model.StapleOnce = pyo.Constraint(model.Days, rule=c_staple_once_day)

    # Constraint: Each recipe used at most once per week except 白米 (shirogome)
    rice_recipes = [r for r in model.Recipes if Recipes[r]['recipeTitle']=='白米']
    def c_recipe_once_week(model,r):
        if r in rice_recipes:
            return sum(model.staple[d,r] + model.main[d,r] + model.side[d,r] + model.soup[d,r] for d in model.Days) <= 6
        else:
            return sum(model.staple[d,r] + model.main[d,r] + model.side[d,r] + model.soup[d,r] for d in model.Days) <= 1
    model.RecipeOnceWeek = pyo.Constraint(model.Recipes, rule=c_recipe_once_week)

    # Link amount to selection variables: amount > 0 only if selected (binary)
    def c_amount_link(model,d,r):
        return model.amount[d,r] <= 10000 * (model.staple[d,r] + model.main[d,r] + model.side[d,r] + model.soup[d,r])
    model.AmountLink = pyo.Constraint(model.Days, model.Recipes, rule=c_amount_link)

    # Restriction: For each item with weight multiples, amount must be multiple of weights
    # Approximate by restricting amount to weights multiples if recipe uses the item
    # Because ItemWeight applies to items, transform recipeId to item weights via RecipeItem
    # We approximate by requiring amount/weight to be integer for the smallest weight multiple if used
    # But Pyomo does not support integer continuous variable directly: instead we add constraints accordingly
    # For simplicity, we represent with variables for each weight multiple and sum to amount

    # Collect recipe to items with weight multiples
    model.ItemNames = pyo.Set(initialize=list(canonical_map.values()))
    model.ItemWithWeight = [i for i in ItemWeight]
    model.WeightSet = pyo.Set(initialize=[(i,w) for i in model.ItemWithWeight for w in ItemWeight[i]['weights']])
    model.WeightMultVars = pyo.Var(model.Days, model.Recipes, model.ItemWithWeight, domain=pyo.NonNegativeIntegers)

    def c_weight_multiples_rule(model,d,r):
        # For each item with weight multiple used in recipe r,
        # sum of weight multiples multiplied by weights == amount used in recipe r times amount times fraction of item in recipe r
        exprs = []
        for it in model.ItemWithWeight:
            # Check if recipe r uses item it or equivalent item in RecipeItem
            # RecipeItem keys have (recipeId, itemName) pairs; check all equivalent item names for it
            eq_items = [k for k,v in canonical_map.items() if v == it]
            used = False
            for eq_it in eq_items:
                if (r, eq_it) in RecipeItem:
                    used = True
                    break
            if not used:
                continue
            amount_item_in_recipe = 0
            for eq_it in eq_items:
                amount_item_in_recipe += RecipeItem.get((r,eq_it),0)
            if amount_item_in_recipe == 0:
                continue
            # amount for item it in recipe r times amount variable for that recipe and day
            # amount[d,r] is total recipe amount for day d and recipe r
            # We require: amount[d,r]*amount_item_in_recipe == sum over weights: weight * WeightMultVars[d,r,it]
            return sum(w*model.WeightMultVars[d,r,it] for w in ItemWeight[it]['weights']) == model.amount[d,r]*amount_item_in_recipe
        return pyo.Constraint.Skip
    model.WeightMultipleConstr = pyo.Constraint(model.Days, model.Recipes, rule=c_weight_multiples_rule)

    # Nutritional constraints:
    # Calculate total nutrition over week and day
    # For each nutrient n and day d sum over recipes chosen quantity * nutrient of recipe
    def total_nutrition_day(model,d,n):
        return sum(model.amount[d,r] * RecipeNutrition[r].get(n,0) for r in model.Recipes)

    # Lower limit constraints excluding calorie and upper limits
    def nutrition_lower_rule(model,d,n):
        if n in lower_limits:
            if n != 'カロリー':
                return total_nutrition_day(model,d,n) >= lower_limits[n]
            else:
                return pyo.Constraint.Skip
        else:
            return pyo.Constraint.Skip
    model.NutritionLower = pyo.Constraint(model.Days, model.Nutrients, rule=nutrition_lower_rule)

    # Upper limit constraints excluding calorie
    def nutrition_upper_rule(model,d,n):
        if n in upper_limits:
            if n != 'カロリー':
                return total_nutrition_day(model,d,n) <= upper_limits[n]
            else:
                return pyo.Constraint.Skip
        else:
            return pyo.Constraint.Skip
    model.NutritionUpper = pyo.Constraint(model.Days, model.Nutrients, rule=nutrition_upper_rule)

    # Calorie bound ±10% per day
    def calorie_rule_lower(model,d):
        if 'カロリー' in exact_limits:
            base = exact_limits['カロリー']
            return total_nutrition_day(model,d,'カロリー') >= base * 0.9
        else:
            return pyo.Constraint.Skip
    model.CalorieLower = pyo.Constraint(model.Days, rule=calorie_rule_lower)

    def calorie_rule_upper(model,d):
        if 'カロリー' in exact_limits:
            base = exact_limits['カロリー']
            return total_nutrition_day(model,d,'カロリー') <= base * 1.1
        else:
            return pyo.Constraint.Skip
    model.CalorieUpper = pyo.Constraint(model.Days, rule=calorie_rule_upper)

    # Objective: minimize number of distinct food ingredients used over the week
    # Introduce binary variables for ingredient use over whole week
    model.ItemUsed = pyo.Var(model.ItemNames, domain=pyo.Binary)

    # Link ItemUsed to actual usage in any recipe in week (sum over days and recipes of usage >= 1 => itemUsed =1)
    def c_item_used_rule(model,it):
        total_usage = 0
        eq_items = [k for k,v in canonical_map.items() if v == it]
        for d in model.Days:
            for r in model.Recipes:
                for eq_it in eq_items:
                    if (r, eq_it) in RecipeItem:
                        total_usage += model.amount[d,r]*RecipeItem[(r,eq_it)]
        return total_usage <= 10000*model.ItemUsed[it]
    model.ItemUsedLink = pyo.Constraint(model.ItemNames, rule=c_item_used_rule)

    # Objective function minimize sum of items used over week
    def obj_rule(model):
        return sum(model.ItemUsed[it] for it in model.ItemNames)
    model.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

    # Solver definition
    model.solver = SolverFactory('cbc')

    return model