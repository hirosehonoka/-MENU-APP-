import pyomo.environ as pyo

def build_model(
    Days,
    Recipes,
    RecipeItem,
    RecipeNutrition,
    NutritionalTarget,
    ItemWeight,
    ItemEqual,
    userInfo,
    regist_item=None,
):
    model = pyo.ConcreteModel()

    # 集合定義
    model.Days = pyo.Set(initialize=Days)
    model.Recipes = pyo.Set(initialize=Recipes)
    model.Items = pyo.Set(initialize=list({item for r in Recipes for item in RecipeItem[r].keys()}))
    model.Nutrients = pyo.Set(initialize=list(NutritionalTarget[userInfo].keys()))
    model.ItemWeightItems = pyo.Set(initialize=list(ItemWeight.keys()))
    model.ItemEqualItems = pyo.Set(initialize=list(ItemEqual.keys()))
    model.Kind1 = pyo.Set(initialize=['staple', 'main', 'soup', 'side'])
    model.Kind2 = pyo.Set(initialize=['rice', 'pasta'])

    # パラメータ定義
    model.RecipeItem = pyo.Param(model.Recipes, model.Items, initialize=lambda m, r, i: RecipeItem[r].get(i, 0), mutable=True)
    model.RecipeNutrition = pyo.Param(model.Recipes, model.Nutrients, initialize=lambda m, r, n: RecipeNutrition[r].get(n, 0), mutable=True)
    model.NutritionalTarget = pyo.Param(model.Nutrients, initialize=lambda m, n: NutritionalTarget[userInfo][n], mutable=True)
    model.ItemWeight = pyo.Param(model.ItemWeightItems, initialize=lambda m, i: ItemWeight[i], mutable=True)
    model.ItemEqual = pyo.Param(model.ItemEqualItems, initialize=lambda m, i: ItemEqual[i], mutable=True)
    model.RecipeKind1 = pyo.Param(model.Recipes, initialize=lambda m, r: Recipes[r]['kind1'], mutable=True)
    model.RecipeKind2 = pyo.Param(model.Recipes, initialize=lambda m, r: Recipes[r]['kind2'], mutable=True)
    model.RecipeTitle = pyo.Param(model.Recipes, initialize=lambda m, r: Recipes[r]['title'], mutable=True)

    # 変数定義
    model.x = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.staple = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.main = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.soup = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.side = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)
    model.used_item = pyo.Var(model.Items, domain=pyo.Binary)

    # 目的関数：食材の種類を最小化
    def obj_rule(model):
        return sum(model.used_item[i] for i in model.Items)
    model.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

    # 制約：各日1食分の献立（主食・主菜・汁物・副菜 or 主食・副菜・汁物）
    def meal_rule(model, d):
        staple = sum(model.staple[d, r] for r in model.Recipes)
        main = sum(model.main[d, r] for r in model.Recipes)
        soup = sum(model.soup[d, r] for r in model.Recipes)
        side = sum(model.side[d, r] for r in model.Recipes)
        rice_pasta = sum(model.x[d, r] for r in model.Recipes if model.RecipeKind2[r] in model.Kind2)
        return staple + main + soup + side + rice_pasta == 4
    model.meal = pyo.Constraint(model.Days, rule=meal_rule)

    # 制約：各区分ごとに1品のみ
    def kind1_rule(model, d, k):
        if k == 'staple':
            return sum(model.staple[d, r] for r in model.Recipes) == 1
        elif k == 'main':
            return sum(model.main[d, r] for r in model.Recipes) == 1
        elif k == 'soup':
            return sum(model.soup[d, r] for r in model.Recipes) == 1
        elif k == 'side':
            return sum(model.side[d, r] for r in model.Recipes) == 1
        else:
            return pyo.Constraint.Skip
    model.kind1 = pyo.Constraint(model.Days, model.Kind1, rule=kind1_rule)

    # 制約：ご飯もの・パスタの場合は主食・副菜・汁物のみ
    def kind2_rule(model, d, r):
        if model.RecipeKind2[r] in model.Kind2:
            return model.main[d, r] == 0
        else:
            return pyo.Constraint.Skip
    model.kind2 = pyo.Constraint(model.Days, model.Recipes, rule=kind2_rule)

    # 制約：各レシピは1週間に1回まで（白米は6回まで）
    def recipe_once_rule(model, r):
        total = sum(model.x[d, r] for d in model.Days)
        if model.RecipeTitle[r] == '白米':
            return total <= 6
        else:
            return total <= 1
    model.recipe_once = pyo.Constraint(model.Recipes, rule=recipe_once_rule)

    # 制約：xとkind1変数の整合性
    def x_kind1_rule(model, d, r):
        return model.x[d, r] == model.staple[d, r] + model.main[d, r] + model.soup[d, r] + model.side[d, r]
    model.x_kind1 = pyo.Constraint(model.Days, model.Recipes, rule=x_kind1_rule)

    # 制約：食材の使用有無
    def used_item_rule(model, i):
        total = sum(model.x[d, r] * model.RecipeItem[r, i] for d in model.Days for r in model.Recipes)
        return model.used_item[i] >= (total > 0)
    model.used_item_con = pyo.Constraint(model.Items, rule=used_item_rule)

    # 制約：ItemEqualの同一食材扱い
    def item_equal_rule(model, i):
        if i in model.ItemEqualItems:
            eq_item = model.ItemEqual[i]
            return sum(model.x[d, r] * model.RecipeItem[r, i] for d in model.Days for r in model.Recipes) == \
                   sum(model.x[d, r] * model.RecipeItem[r, eq_item] for d in model.Days for r in model.Recipes)
        else:
            return pyo.Constraint.Skip
    model.item_equal = pyo.Constraint(model.ItemEqualItems, rule=item_equal_rule)

    # 制約：ItemWeightの倍数
    def item_weight_rule(model, i):
        if i in model.ItemWeightItems:
            total = sum(model.x[d, r] * model.RecipeItem[r, i] for d in model.Days for r in model.Recipes)
            return total % model.ItemWeight[i] == 0
        else:
            return pyo.Constraint.Skip
    model.item_weight = pyo.Constraint(model.ItemWeightItems, rule=item_weight_rule)

    # 制約：regist_itemで指定された食材は必ず使い切る
    if regist_item:
        def regist_item_rule(model, i):
            if i in regist_item:
                total = sum(model.x[d, r] * model.RecipeItem[r, i] for d in model.Days for r in model.Recipes)
                return total == regist_item[i]
            else:
                return pyo.Constraint.Skip
        model.regist_item = pyo.Constraint(model.Items, rule=regist_item_rule)

    # 制約：栄養素の範囲
    def nutrition_rule(model, n):
        target = model.NutritionalTarget[n]
        total = sum(model.x[d, r] * model.RecipeNutrition[r, n] for d in model.Days for r in model.Recipes)
        if n.endswith('_下限'):
            nutrient = n.replace('_下限', '')
            if nutrient == 'たんぱく質':
                cal = sum(model.x[d, r] * model.RecipeNutrition[r, 'カロリー'] for d in model.Days for r in model.Recipes)
                return cal * (target / 400) <= sum(model.x[d, r] * model.RecipeNutrition[r, nutrient] for d in model.Days for r in model.Recipes)
            elif nutrient == '脂質':
                cal = sum(model.x[d, r] * model.RecipeNutrition[r, 'カロリー'] for d in model.Days for r in model.Recipes)
                return cal * (target / 900) <= sum(model.x[d, r] * model.RecipeNutrition[r, nutrient] for d in model.Days for r in model.Recipes)
            elif nutrient == '炭水化物':
                cal = sum(model.x[d, r] * model.RecipeNutrition[r, 'カロリー'] for d in model.Days for r in model.Recipes)
                return cal * (target / 400) <= sum(model.x[d, r] * model.RecipeNutrition[r, nutrient] for d in model.Days for r in model.Recipes)
            else:
                return target <= total
        elif n.endswith('_上限'):
            nutrient = n.replace('_上限', '')
            if nutrient == 'たんぱく質':
                cal = sum(model.x[d, r] * model.RecipeNutrition[r, 'カロリー'] for d in model.Days for r in model.Recipes)
                return sum(model.x[d, r] * model.RecipeNutrition[r, nutrient] for d in model.Days for r in model.Recipes) <= cal * (target / 400)
            elif nutrient == '脂質':
                cal = sum(model.x[d, r] * model.RecipeNutrition[r, 'カロリー'] for d in model.Days for r in model.Recipes)
                return sum(model.x[d, r] * model.RecipeNutrition[r, nutrient] for d in model.Days for r in model.Recipes) <= cal * (target / 900)
            elif nutrient == '炭水化物':
                cal = sum(model.x[d, r] * model.RecipeNutrition[r, 'カロリー'] for d in model.Days for r in model.Recipes)
                return sum(model.x[d, r] * model.RecipeNutrition[r, nutrient] for d in model.Days for r in model.Recipes) <= cal * (target / 400)
            else:
                return total <= target
        elif n == 'カロリー':
            cal_total = sum(model.x[d, r] * model.RecipeNutrition[r, n] for d in model.Days for r in model.Recipes)
            return pyo.inequality(0.9 * target, cal_total, 1.1 * target)
        else:
            return total >= target
    model.nutrition = pyo.Constraint(model.Nutrients, rule=nutrition_rule)

    return model