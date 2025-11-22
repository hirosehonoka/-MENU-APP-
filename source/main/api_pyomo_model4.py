import pyomo.environ as pyo

def build_model(
    days,
    recipe_dict,
    recipe_ids,
    recipeitem_dict,
    filtered_recipe_nutritions,
    nutritionaltarget_dict,
    itemweight_dict,
    itemequal_dict,
    menstruation,
    regist_item,
    use_pfc=True
):
    model = pyo.ConcreteModel()

    model.Days = pyo.Set(initialize=days)
    model.Recipes = pyo.Set(initialize=recipe_ids)

    # --- Helper sets for kinds ---
    def kind1_map_init(m, r):
        return recipe_dict[r]['data']['kind1']
    model.kind1_map = pyo.Param(model.Recipes, initialize=kind1_map_init, within=pyo.Any)

    def kind2_map_init(m, r):
        return recipe_dict[r]['data']['kind2']
    model.kind2_map = pyo.Param(model.Recipes, initialize=kind2_map_init, within=pyo.Any)

    # --- Identify staple recipes with kind2 in {ご飯もの, パスタ, カレー, 鍋} ---
    staple_special_kind2 = {'ご飯もの', 'パスタ', 'カレー', '鍋'}
    model.StapleSpecialRecipes = pyo.Set(initialize=[r for r in recipe_ids if recipe_dict[r]['data']['kind1']=='staple' and recipe_dict[r]['data']['kind2'] in staple_special_kind2])

    # --- Variables ---
    # Binary variables for recipe selection per day and kind1 category
    model.x = pyo.Var(model.Days, model.Recipes, domain=pyo.Binary)

     #修正部分（食材リスト参照部の修正）
    all_ingredients = set()
    for items in recipeitem_dict.values():
        all_ingredients.update(k for k, v in items.items() if v > 0)
    model.Ingredients = pyo.Set(initialize=sorted(all_ingredients))


    # Continuous variable for amount of each item used in total (for regist_item constraints)
    model.item_used = pyo.Var(itemweight_dict.keys(), domain=pyo.Binary)

    #　修正部分（週全体で使ったか判定するバイナリ変数を定義）
    model.y_item = pyo.Var(model.Ingredients, domain=pyo.Binary) 

    # --- Constraint: Each day must have a valid menu composition ---
    def staple_count_rule(m, d):
        return sum(m.x[d, r] for r in model.Recipes if m.kind1_map[r] == 'staple') == 1
    model.StapleCount = pyo.Constraint(model.Days, rule=staple_count_rule)

    def main_count_rule(m, d):
        # main count = 1 if no staple_special recipe selected, else 0
        staple_special_sum = sum(m.x[d, r] for r in model.StapleSpecialRecipes)
        # main count + staple_special_sum == 1
        return sum(m.x[d, r] for r in model.Recipes if m.kind1_map[r] == 'main') + staple_special_sum == 1
    model.MainCount = pyo.Constraint(model.Days, rule=main_count_rule)

    def side_count_rule(m, d):
        return sum(m.x[d, r] for r in model.Recipes if m.kind1_map[r] == 'side') == 1
    model.SideCount = pyo.Constraint(model.Days, rule=side_count_rule)

    def soup_count_rule(m, d):
        return sum(m.x[d, r] for r in model.Recipes if m.kind1_map[r] == 'soup') == 1
    model.SoupCount = pyo.Constraint(model.Days, rule=soup_count_rule)

    # --- Constraint: Each recipe used at most once in the week except staple with kind2 ご飯もの can be used up to 7 times ---
    def recipe_usage_rule(m, r):
        if r in m.StapleSpecialRecipes:
            return sum(m.x[d, r] for d in m.Days) <= 7
        else:
            return sum(m.x[d, r] for d in m.Days) <= 1
    model.RecipeUsage = pyo.Constraint(model.Recipes, rule=recipe_usage_rule)

    # --- Constraint: nutrition bounds per day ---
    # Extract nutrition names and bounds from nutritionaltarget_dict for userInfo
    # Find matching nutrition target for userInfo
    target = next(iter(nutritionaltarget_dict.values()))
    nutritionals = target['nutritionals']  

    #制約条件調整用・栄養条件の確認（カロリーのみ考慮） 
    target = next(iter(nutritionaltarget_dict.values()))
    nutritionals = target['nutritionals']

    cal_val = nutritionals.get('カロリー', None)

    pfc_keys = [
        'カロリー(kcal)',
        'たんぱく質(g)',
        '脂質(g)',
        '炭水化物(g)',
    ]

    other_keys = [
        "食物繊維(g)",
        "カルシウム(mg)",
        "ビタミンA(μg)",
        "ビタミンD(μg)",
        "ビタミンC(mg)",
        "ビタミンB₁(mg)",
        "ビタミンB₂(mg)",
        "鉄(mg)"
    ]

    # 実際にモデルに入れる栄養素のリスト
    if use_pfc:
        nut_keys = pfc_keys + other_keys
    else:
        nut_keys = other_keys

    def nutrition_rule(m, nut):
        total_val = sum(
            m.x[d, r] * filtered_recipe_nutritions[r].get(nut, 0)
            for d in m.Days
            for r in m.Recipes
        )

        if nut == 'カロリー(kcal)':
            lower = cal_val * 0.9
            upper = cal_val * 1.1
            return pyo.inequality(lower, total_val, upper)

        if nut == 'たんぱく質(g)':
            p_lb = cal_val * (nutritionals.get('たんぱく質_下限',0)/100) / 4
            p_ub = cal_val * (nutritionals.get('たんぱく質_上限',0)/100) / 4
            return pyo.inequality(p_lb, total_val, p_ub)

        if nut == '脂質(g)':
            f_lb = cal_val * (nutritionals.get('脂質_下限',0)/100) / 9
            f_ub = cal_val * (nutritionals.get('脂質_上限',0)/100) / 9
            return pyo.inequality(f_lb, total_val, f_ub)

        if nut == '炭水化物(g)':
            c_lb = cal_val * (nutritionals.get('炭水化物_下限',0)/100) / 4
            c_ub = cal_val * (nutritionals.get('炭水化物_上限',0)/100) / 4
            return pyo.inequality(c_lb, total_val, c_ub)

        # それ以外の栄養素
        lower_key = f"{nut.split('(')[0]}_下限"
        upper_key = f"{nut.split('(')[0]}_上限"
        lower = nutritionals.get(lower_key, None)
        upper = nutritionals.get(upper_key, None)

        # 鉄の月経対応
        if nut == '鉄(mg)':
            if menstruation == 'あり':
                lower = nutritionals.get('鉄・月経時_下限', None)
            else:
                lower = nutritionals.get('鉄_下限', None)
            upper = nutritionals.get('鉄_上限', None)

        if lower is None and upper is None:
            return pyo.Constraint.Skip
        if lower is None:
            return pyo.inequality(None, total_val, upper)
        if upper is None:
            return pyo.inequality(lower, total_val, None)
        return pyo.inequality(lower, total_val, upper)

    model.NutritionConstraints = pyo.Constraint(nut_keys, rule=nutrition_rule)

    def items_per_day_rule(m, d):
        return pyo.inequality(3, sum(m.x[d, r] for r in m.Recipes), 4)

    model.ItemsPerDay = pyo.Constraint(model.Days, rule=items_per_day_rule)

    # 未使用量（使い残し）を表す変数
    model.Unused = pyo.Var(regist_item.keys(), domain=pyo.NonNegativeReals)

    #使った量 + 未使用 = 登録量 の制約
    def used_amount_rule(m, i):
        total_used = sum(
            m.x[d, r] * recipeitem_dict[r].get(i, 0)
            for d in m.Days for r in m.Recipes
        )
        return total_used + m.Unused[i] == regist_item[i]

    model.RegistItemBalance = pyo.Constraint(regist_item.keys(), rule=used_amount_rule)

    # 登録食材を使ったかどうか（0/1）
    model.y_regist = pyo.Var(model.Ingredients, domain=pyo.Binary)
    def y_regist_rule(m, i):
        # 1週間のどこかで i が使われていたら 1
        total_used = sum(
            m.x[d, r] * recipeitem_dict[r].get(i, 0)
            for d in m.Days for r in m.Recipes
        )
        # total_used > 0 → y_regist[i] = 1 を言いたい
        # Pyomo では Big-M の形にする
        return total_used <= BIG_M * m.y_regist[i]

    BIG_M = 1000
    model.YRegistConstraint = pyo.Constraint(model.Ingredients, rule=y_regist_rule)

    # 指定の食材の使用量を指定の値の倍数にするための制約
    model.e = pyo.Var(model.Days, model.Recipes, model.Ingredients, within=pyo.NonNegativeReals)
    def multiple_soft_rule(m, d, r, i):
        # 倍数ルールの対象外の食材はスキップ
        if i not in itemweight_dict:
            return pyo.Constraint.Skip

        # 一つ目の重さ（基準重量）
        weight_list = itemweight_dict[i].get("weights", [])
        if not weight_list:
            return pyo.Constraint.Skip
        weight = weight_list[0]

        # レシピで使う食材量（g） ※ここは整数
        amount = recipeitem_dict[r].get(i, 0)

        # x[d,r] = 0 → 使わない → 誤差も 0
        if amount == 0:
            return m.e[d, r, i] >= 0

        # 最も近い weight の倍数
        mult = round(amount / weight)

        # 誤差は以下を満たす必要あり
        return m.e[d, r, i] >= m.x[d, r] * amount - (weight * mult)

    def multiple_soft_rule2(m, d, r, i):
        if i not in itemweight_dict:
            return pyo.Constraint.Skip

        weight = itemweight_dict[i]["weights"][0]
        amount = recipeitem_dict[r].get(i, 0)

        return m.e[d,r,i] >= weight * round(amount / weight) - m.x[d,r] * amount

    model.MultipleSoft1 = pyo.Constraint(model.Days, model.Recipes, model.Ingredients, rule=multiple_soft_rule)
    model.MultipleSoft2 = pyo.Constraint(model.Days, model.Recipes, model.Ingredients, rule=multiple_soft_rule2)

    # 同一食材の紐付け対策
    target_items = set(itemweight_dict.keys()) | set(itemequal_dict.keys())

    eq_classes = []
    visited = set()
    for i in target_items:
        if i in visited:
            continue
        group = set([i])
        if i in itemequal_dict:
            group.update(itemequal_dict[i]['equals'])
        for j in list(group):
            if j in itemequal_dict:
                group.update(itemequal_dict[j]['equals'])
        group = frozenset(group)
        eq_classes.append(group)
        visited.update(group)

    # Map item to representative
    rep_map = {}
    for group in eq_classes:
        rep = sorted(group)[0]
        for i in group:
            rep_map[i] = rep

    # Redefine y_item and item_used by representative
    model.y_item_rep = pyo.Var(set(rep_map.values()), domain=pyo.Binary)
    model.item_used_rep = pyo.Var(set(rep_map.values()), domain=pyo.NonNegativeReals)

    # Link original item_used to rep sums
    def item_used_rep_rule(m, i):
        if i not in itemweight_dict:
            return pyo.Constraint.Skip   # itemweight_dict にない食材は無視
        rep = rep_map[i]
        return m.item_used[i] <= m.item_used_rep[rep]
    model.ItemUsedRepLink = pyo.Constraint(target_items, rule=item_used_rep_rule)

    # Link rep item_used to y_item_rep
    def item_used_y_link_rule(m, rep):
        M = 1e6
        return m.item_used_rep[rep] <= M * m.y_item_rep[rep]
    model.ItemUsedYLink = pyo.Constraint(set(rep_map.values()), rule=item_used_y_link_rule)

    # # Objective updated to sum over y_item_rep
    # model.obj.expr = sum(model.y_item_rep[rep] for rep in model.y_item_rep)

    # --- Link item_used to recipeitem_dict and x ---
    def item_used_calc_rule(m, i):
        if i not in itemweight_dict:
            return pyo.Constraint.Skip
        total = sum(
            m.x[d,r] * recipeitem_dict[r].get(i,0)
            for d in m.Days for r in m.Recipes
        )
        return m.item_used[i] >= total
    model.ItemUsedCalc = pyo.Constraint(itemweight_dict.keys(), rule=item_used_calc_rule)

    # ご飯レシピの集合
    model.GohanRecipes = [r for r in model.Recipes if model.kind2_map[r] == 'ご飯']
    # ご飯以外のレシピ
    model.NonGohanRecipes = [r for r in model.Recipes if model.kind2_map[r] != 'ご飯']
    # ご飯レシピ → 7回まで
    def limit_gohan_rule(m, r):
        return sum(m.x[d, r] for d in m.Days) <= 7
    model.LimitGohan = pyo.Constraint(model.GohanRecipes, rule=limit_gohan_rule)

    # ご飯以外レシピ → 1回まで
    def limit_non_gohan_rule(m, r):
        return sum(m.x[d, r] for d in m.Days) <= 1
    model.LimitNonGohan = pyo.Constraint(model.NonGohanRecipes, rule=limit_non_gohan_rule)

    #　修正部分（使った場合のみy_item=1となるリンク条件）
    def ingredient_link_rule(m, i):
    # 使われるならy_item[i]=1。どのレシピ、どの日でもitem>0なら該当
    # recipeitem_dict[r][i]>0かつx[d,r]=1なら使用
        return sum(
            m.x[d, r] * recipeitem_dict[r].get(i, 0)
            for d in m.Days for r in m.Recipes
        ) <= 1e6 * m.y_item[i]
    model.IngredientLink = pyo.Constraint(model.Ingredients, rule=ingredient_link_rule)

    #　修正部分（目的関数：週に使った食材の種類の最小化）   
    # weight_item : 食材種類削減の重み
    # weight_regist : 登録食材を使うメリットの重み

    weight_item = 1
    weight_regist = 10   # 食材を使うほど目的が下がる
    penalty_not_use = 50      # 登録食材を使わない場合は重く罰する
    weight_multiple = 3         # 倍数使用は弱いペナルティ

    model.obj = pyo.Objective(
        expr = sum(weight_item * model.y_item[i] for i in model.Ingredients)
            - sum(weight_regist * model.y_regist[i] for i in model.Ingredients)
            + penalty_not_use * sum(1 - model.y_regist[i] for i in model.Ingredients)
            + weight_multiple * sum(model.e[d,r,i] for d in model.Days for r in model.Recipes for i in model.Ingredients),
        sense = pyo.minimize
    )
    # 修正部分（作成した献立を返す）
    def extract_day_menus_with_categories(model, recipe_dict):
        """
        Pyomoモデルの解から、日ごとの選択レシピを抽出する
        """
        result = {}
        for d in model.Days:
            daily_recipes = []
            for r in model.Recipes:
                try:
                    val = pyo.value(model.x[d, r])
                    if val is not None and val > 0.5:
                        # recipe_dictのキーがstr/int混在していても対応
                        r_key = str(r) if str(r) in recipe_dict else int(r) if int(r) in recipe_dict else None
                        if r_key:
                            daily_recipes.append(recipe_dict[r_key])
                        else:
                            print(f"⚠️ recipe_dict に {r} が存在しません")
                except Exception as e:
                    print(f"❌ extract error (Day={d}, Recipe={r}): {e}")
            result[f'menu{d}'] = daily_recipes
        print("=== day_menus 抽出完了 ===")
        for k, v in result.items():
            print(k, len(v))
        return result

    # --- Solver ---
    model.solver = pyo.SolverFactory('cbc')

    return model