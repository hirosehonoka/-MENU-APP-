from flask import Flask,render_template,request,redirect,flash,url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.automap import automap_base
from sqlalchemy import  cast, BigInteger,literal,select,union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from flask_login import UserMixin,LoginManager,login_user,login_required,logout_user,current_user
from werkzeug.security import generate_password_hash,check_password_hash
import os,json,requests,re
from collections import defaultdict
from dotenv import load_dotenv
from perplexity import Perplexity
from pyomo.environ import SolverFactory


app = Flask(__name__)

app.jinja_env.globals['getattr'] = getattr

app.config["SECRET_KEY"] = os.urandom(24)

load_dotenv() 
client = Perplexity() # Uses PERPLEXITY_API_KEY from .env file

#ログイン管理システム
login_manager = LoginManager()
login_manager.init_app(app)

db = SQLAlchemy()
DB_INFO = {
    'user':'postgres',
    'password':'',
    'host':'localhost',
    'name':'postgres'
}
SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg://{user}:{password}:@{host}/{name}'.format(**DB_INFO)
app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
db.init_app(app)

Base = automap_base()
with app.app_context():
    Base.prepare(db.engine, reflect=True)
RecipeUrl = Base.classes.recipeUrls
Menu = Base.classes.menu
ItemEqual = Base.classes.itemEquals
RecipeItem = Base.classes.recipeItems
RecipeNutrition = Base.classes.recipeNutritions
Recipe = Base .classes.recipes
ItemWeight = Base .classes .itemWeights
NutritionalTarget = Base .classes.nutritionalTargets
User = Base.classes.user

with app.app_context():
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db.engine)
    session = SessionLocal()

#現在のユーザを識別する
@login_manager.user_loader
def load_user(user_id):
    user = db.session.query(User).get(int(user_id))
    if user:
        return UserWrapper(user)
    return None

#プロンプト用テキストファイルを読み込む
def data2str(data):
    return str(data)
def generate_prompt(planning_data):
    base_dir = os.path.dirname(__file__)
    prompt_file_path = os.path.join(base_dir, "prompt_test1.txt")
    with open(prompt_file_path, encoding="utf-8") as f:
        prompt_template = f.read()
    return prompt_template.format(problem_data=str(planning_data))

#MarkDown削除用
def extract_python_code(text):
    # Markdownコードブロック (```python ... ```
    m = re.search(r"```(?:python|パイソン)?\s*([\s\S]*?)```", text, re.DOTALL)
    if m:
        code_str = m.group(1)
    else:
        code_str = text
    return code_str.strip()

#辞書化関数・kind1の補完
def as_dict(row):
    out = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    # 万一欠損があれば補完
    if 'kind1' not in out:
        out['kind1'] = ''
    return out

#日毎の献立
def extract_day_menus_with_categories(model, recipe_list):
    day_menus = {}
    # インデックスが range(1,8) などの場合はlist化してループ
    for d in list(model.Days):
        menu = {}
        for cat in ['stample', 'main', 'soup', 'side']:
            if hasattr(model, cat):
                var = getattr(model, cat)
                # 値が最大のレシピを抽出
                selected_r = None
                max_val = -float('inf')
                for r in list(model.Recipes):
                    v = var[d, r].value
                    if v is not None and v > max_val:
                        max_val = v
                        selected_r = r
                if max_val >= 0.5:  # 0/1バイナリの場合。floatなら>=0.5で判定
                    # rがIDならタイトル対応（recipe_list中からrを探す）
                    recipe_title = None
                    for rec in recipe_list:
                        if rec.get('recipeId') == selected_r:
                            recipe_title = rec.get('recipeTitle')
                            break
                    menu[cat] = {'id': selected_r, 'title': recipe_title}
                else:
                    menu[cat] = None  # 未選択の場合
        day_menus[f"menu{d}"] = menu
    return day_menus


class User(UserMixin,db.Model):
    userId = db.Column(db.Integer,primary_key=True)
    userName = db.Column(db.String(20),nullable=False,unique=True)
    password = db.Column(db.String(200),nullable=False)
    userInfo = db.Column(JSONB,nullable=False)

# class RecipeUrl(db.Model):
#     recipeId = db.Column(db.Integer,primary_key=True)
#     recipeTitle = db.Column(db.String,nullable=False)
#     recipeUrl = db.Column(db.String,nullable=True)
#     foodImageUrl= db.Column(db.String,nullable=False)

# class Menu(db.Model):
#     menuId = db.Column(db.Integer,primary_key=True)
#     menu1 = db.Column(JSONB,nullable=False)
#     menu2 = db.Column(JSONB,nullable=False)
#     menu3 = db.Column(JSONB,nullable=False)
#     menu4 = db.Column(JSONB,nullable=False)
#     menu5 = db.Column(JSONB,nullable=False)
#     menu6 = db.Column(JSONB,nullable=False)
#     menu7 = db.Column(JSONB,nullable=False)
#     userName = db.Column(db.String(20),nullable=False)
#     tokyo_timezone = pytz.timezone('Asia/Tokyo')
#     createdAt = db.Column(db.DateTime,nullable=False,default=datetime.now)

# class ItemEqual(db.Model):
#     itemName = db.Column(db.String,primary_key=True)
#     equals = db.Column(JSONB,nullable=False)

# class RecipeItem(db.Model):
#     recipeId = db.Column(db.Integer,primary_key=True)
#     items = db.Column(JSONB,nullable=False)

class UserWrapper(UserMixin):
    def __init__(self, user):
        self.user = user

    def __getattr__(self, name):
        return getattr(self.user, name)

    def get_id(self):
        # userIdカラムを文字列にして返す
        return str(self.user.userId)

    @property
    def is_active(self):
        return True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False
    
@app.route("/")
def home():
    return render_template("home.html", show_navbar=False)
    
@app.route("/menu")
@login_required
def show_menus():
    weekly_data = []
    menu = db.session.query(Menu).filter_by(userName=current_user.userName).first()

    if menu is None:
        return render_template("menu.html", weekly_data=[], show_navbar=True)

    queries = []
    idx = 0

    for menu_col in ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']:
        menu_json = getattr(menu, menu_col, {})
        for meal_type in ['staple', 'main', 'side', 'soup']:
            val = menu_json.get(meal_type)
            if val is None:  # nullはスキップ
                continue

            try:
                recipe_id = int(val) if not hasattr(val, 'astext') else int(val.astext)
            except (ValueError, TypeError):
                continue

            idx += 1

            query = (
                db.session.query(
                    RecipeUrl.recipeTitle.label('recipeTitle'),
                    RecipeUrl.recipeUrl.label('recipeUrl'),
                    RecipeUrl.foodImageUrl.label('foodImageUrl'),
                    literal(f'{menu_col}_{meal_type}').label('meal_type'),
                )
                .join(Menu, RecipeUrl.recipeId == cast(getattr(Menu, menu_col)[meal_type].astext, BigInteger))
                .filter(Menu.userName == current_user.userName)
                .filter(RecipeUrl.recipeId == recipe_id)
            )
            queries.append(query)

    if not queries:
        return render_template("menu.html", weekly_data=[], show_navbar=True)

    full_query = queries[0]
    for q in queries[1:]:
        full_query = full_query.union_all(q)

    core_queries = [q.statement for q in queries]
    full_union = union_all(*core_queries).alias('full_union')

    stmt = select(
        full_union.c.recipeTitle,
        full_union.c.recipeUrl,
        full_union.c.foodImageUrl,
        full_union.c.meal_type,
    )

    results = db.session.execute(stmt).fetchall()

    grouped = defaultdict(list)
    for r in results:
        menu_col = r.meal_type.split('_')[0] 
        grouped[menu_col].append(r)

    menu_order = ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']
    weekly_data = [grouped[m] for m in menu_order]

    return render_template("menu.html", weekly_data=weekly_data, current_page='menu', show_navbar=True)

@app.route("/item")
@login_required
def show_item():
    aggregated_ingredients = {}
    menu = db.session.query(Menu).filter_by(userName=current_user.userName).first()
    if menu is None:
        return render_template("item.html", ingredients=aggregated_ingredients, total_types=0, current_page='item', show_navbar=True)

    # menu1〜menu7のすべてのrecipeIdを取得（中身が例えば {staple:123, main:456} のような構造を想定）
    recipe_ids = []
    for menu_col in ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']:
        menu_json = getattr(menu, menu_col, {})
        for meal_type in ['staple', 'main', 'side', 'soup']:
            val = menu_json.get(meal_type)
            if val is None:
                continue
            try:
                recipe_id = int(val) if not hasattr(val, 'astext') else int(val.astext)
            except (ValueError, TypeError):
                continue
            recipe_ids.append(recipe_id)

    recipe_ids = list(set(recipe_ids))

    # ItemEqualの辞書作成: 等価食材名 -> 代表名
    item_equals = db.session.query(ItemEqual).all()
    item_equal_map = {}
    for eq in item_equals:
        equals_list = eq.equals.split(',') if eq.equals else []
        for k in equals_list:
            item_equal_map[k] = eq.itemName
        item_equal_map[eq.itemName] = eq.itemName

    # recipeIdごとにitemsを集計
    for rid in recipe_ids:
        recipe_item = db.session.query(RecipeItem).filter(RecipeItem.recipeId == rid).first()
        if not recipe_item:
            continue
        for ing_name, qty in recipe_item.items.items():
            # 代表名に変換
            rep_name = item_equal_map.get(ing_name, ing_name)

            # 加算
            aggregated_ingredients[rep_name] = aggregated_ingredients.get(rep_name, 0) + qty

    total_types = len(aggregated_ingredients)

    return render_template('item.html', ingredients=aggregated_ingredients, total_types=total_types, current_page='item', show_navbar=True)

@app.route('/createmenu', methods=['GET','POST'])
@login_required
def create_menu():
    # 1. ログインユーザ情報取得
    user = db.session.query(User).filter_by(userName=current_user.userName).first()
    if not user or not user.userInfo:
        flash("ユーザーターゲットが登録されていません")
        return redirect(url_for('index'))
    user_userInfo = user.userInfo # jsonb型。Pythonではdict想定
    
    # 2. NutritionalTargetからマッチングレコード探索
    # 年齢、性別、運動レベル
    userInfo_conditions = user_userInfo.copy()
    age = userInfo_conditions.get('年齢', None)
    gender = userInfo_conditions.get('性別', None)
    activity = userInfo_conditions.get('運動レベル', None)

    # 「75歳以上」かつ「運動レベル 高い」なら運動レベルを「ふつう」に
    activity_query = activity
    if age and ('75' in age and activity == '高い'):
        activity_query = 'ふつう'

    # SQLAlchemyによるjsonbフィールド完全一致 AND 年齢・性別・運動レベル条件
    nt = db.session.query(NutritionalTarget).filter(
        NutritionalTarget.userInfo['年齢'].astext == str(age),
        NutritionalTarget.userInfo['性別'].astext == str(gender),
        NutritionalTarget.userInfo['運動レベル'].astext == str(activity_query)
    ).first()
    if nt is None:
        flash("栄養ターゲットが見つかりません")
        return redirect(url_for('index'))
    nutritional = nt.nutritionals
    
    # 3. レシピ・食材・関連データ一式をIDごとにまとめて取得
    recipes = db.session.query(Recipe).all()
    recipe_nutritions = {r.recipeId: r.nutritions for r in db.session.query(RecipeNutrition).all()}
    recipe_items = {ri.recipeId: ri.items for ri in db.session.query(RecipeItem).all()}
    item_weights = {iw.itemName: iw.weights for iw in db.session.query(ItemWeight).all()}
    item_equals = {ie.itemName: ie.equals for ie in db.session.query(ItemEqual).all()}

    # # 4. プロンプト文生成
    # # データのまとめ
    # planning_data = {
    #     "nutritional_targets": nutritional,
    #     "recipes": [r.data for r in recipes],
    #     "recipe_nutritions": recipe_nutritions,
    #     "recipe_items": recipe_items,
    #     "item_weights": item_weights,
    #     "item_equals": item_equals,
    # }
    # solution_prompt = generate_prompt(planning_data)


    # optimization_input = client.chat.completions.create(
    #     messages=[{"role": "user", "content": solution_prompt}],
    #     model="sonar"
    # )


    # # 6. Pyomo（+cbc）最適化
    # pyomo_code_str_raw = optimization_input.choices[0].message.content
    # pyomo_code_str = extract_python_code(pyomo_code_str_raw)
    # print('API出力内容2:')
    # print(pyomo_code_str)

    #API出力コードの読み込み(ソルバー周辺調整用)
    base_dir = os.path.dirname(__file__)  # menuapp.pyのある場所
    api_file_path = os.path.join(base_dir, "api_pyomo_model.py")
    with open(api_file_path, encoding='utf-8') as f:
        pyomo_code_str = f.read()

    # SQLAlchemyからリストやディクショナリでデータ取得
    recipe_dict = {r.recipeId: as_dict(r) for r in db.session.query(Recipe).all()}
    itemweight_dict = {iw.itemName: as_dict(iw) for iw in db.session.query(ItemWeight).all()}
    itemequal_dict = {ie.itemName: as_dict(ie) for ie in db.session.query(ItemEqual).all()}
    recipeitem_dict = {}
    recipeitem_list = [as_dict(ri) for ri in db.session.query(RecipeItem).all()]
    for rec in recipeitem_list:
        rid = rec['recipeId']
        items = rec.get('items', {})  # itemsカラムが空のときも考慮
        for item, qty in items.items():
            recipeitem_dict[(rid, item)] = qty
    recipenutrition_dict = {rn.recipeId: as_dict(rn) for rn in db.session.query(RecipeNutrition).all()}
    nutritionaltarget_dict = {"nutritionals": nt.nutritionals,  "userInfo": nt.userInfo}
    user = db.session.query(User).filter_by(userName=current_user.userName).first()
    userInfo = user.userInfo

    for v in recipe_dict.values():
        if 'kind1' not in v:
            v['kind1'] = ''
        if 'kind2' not in v:
            v['kind2'] = ''

    scope = {
        'Recipe': recipe_dict,
        'ItemWeight': itemweight_dict,
        'ItemEqual': itemequal_dict,
        'RecipeItem': recipeitem_dict,
        'RecipeNutrition': recipenutrition_dict,
        'NutritionalTarget': nutritionaltarget_dict,
        'userInfo': userInfo
    }

    exec(pyomo_code_str, scope)
    build_model = scope['build_model']

    Days = list(range(7)) 
    Recipes = list(recipe_dict.keys())

    model = build_model(
        Days,recipe_dict, recipeitem_dict, recipenutrition_dict, nutritionaltarget_dict, userInfo,
        itemweight_dict, itemequal_dict
    )

    model.MealCompConstr = pyo.ConstraintList()
    for d in model.Days:
        expr_stample = sum(model.stample[d, r] for r in model.Recipes)
        expr_main = sum(model.main[d, r] for r in model.Recipes)
        expr_soup = sum(model.soup[d, r] for r in model.Recipes)
        expr_side = sum(model.side[d, r] for r in model.Recipes)
        is_rice_or_pasta = sum(model.stample[d, r] for r in RiceOrPastaSet)
        model.MealCompConstr.add(expr_stample == 1)
        model.MealCompConstr.add(expr_main == 1)
        model.MealCompConstr.add(expr_soup == 1)
        model.MealCompConstr.add(expr_side == 1 - is_rice_or_pasta)


    cbc_path = "/Users/hiruse/cbc/bin/cbc"
    solver = SolverFactory('cbc', executable=cbc_path)  # フルパスを指定
    results = solver.solve(model)
    day_menus = extract_day_menus_with_categories(model) 

    # 7. 曜日ごとのMenuレコード保存
    menu_obj = Menu(
        userName=current_user.userName,
        menu1=json.dumps(day_menus.get('menu1', {})),
        menu2=json.dumps(day_menus.get('menu2', {})),
        menu3=json.dumps(day_menus.get('menu3', {})),
        menu4=json.dumps(day_menus.get('menu4', {})),
        menu5=json.dumps(day_menus.get('menu5', {})),
        menu6=json.dumps(day_menus.get('menu6', {})),
        menu7=json.dumps(day_menus.get('menu7', {}))
    )
    db.session.add(menu_obj)
    db.session.commit()

    return redirect('/menu', menuId=menu_obj.id)


# @app.route("/nutritional")
# @login_required
# def show_nutritional():
#     menu = db.session.query(Menu).filter_by(userName=current_user.userName).first()
#     if menu is None:
#         return render_template("nutritional.html",  current_page='nutritional', show_navbar=True)

#     # menu1〜menu7のすべてのrecipeIdを取得（中身が例えば {staple:123, main:456} のような構造を想定）
#     recipe_ids = []
#     for menu_col in ['menu1', 'menu2', 'menu3', 'menu4', 'menu5', 'menu6', 'menu7']:
#         menu_json = getattr(menu, menu_col, {})
#         for meal_type in ['staple', 'main', 'side', 'soup']:
#             val = menu_json.get(meal_type)
#             if val is None:
#                 continue
#             try:
#                 recipe_id = int(val) if not hasattr(val, 'astext') else int(val.astext)
#             except (ValueError, TypeError):
#                 continue
#             recipe_ids.append(recipe_id)

#     recipe_ids = list(set(recipe_ids))

@app.route("/signup",methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        userName = request.form.get('userName')
        password = request.form.get('password')
        hashed_pass = generate_password_hash(password)
        userAge = request.form.get('userAge')
        userGender = request.form.get('userGender')
        userExerciseLevel = request.form.get('userExerciseLevel')
        userInfo ={"年齢":userAge,"性別":userGender,"運動レベル":userExerciseLevel}
        user = User(userName=userName,password=hashed_pass,userInfo=userInfo)
        db.session.add(user)
        db.session.commit()
        return redirect('/login')
    elif request.method == 'GET':
        return render_template('signup.html', show_navbar=False)
    
@app.route("/userupdate", methods=['GET', 'POST'])
@login_required
def user_update():
    user = db.session.query(User).get(current_user.get_id())

    if request.method == 'POST':
        userAge = request.form.get('userAge')
        userExerciseLevel = request.form.get('userExerciseLevel')

        if user and user.userInfo:
            # userInfoは辞書と仮定
            user.userInfo['年齢'] = userAge
            user.userInfo['運動レベル'] = userExerciseLevel

            db.session.commit()
        return redirect('/menu')

    else:  # GET
        userAge_selected = user.userInfo.get('年齢') if user and user.userInfo else None
        userExerciseLevel_selected = user.userInfo.get('運動レベル') if user and user.userInfo else None

        return render_template(
            'userupdate.html',
            userAge_selected=userAge_selected,
            userExerciseLevel_selected=userExerciseLevel_selected,
            current_page='userupdate',
            show_navbar=True
        )

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method == 'POST':
        userName = request.form.get('userName')
        password = request.form.get('password')
        user = db.session.query(User).filter_by(userName=userName).first()
        print(user.userName)
        if check_password_hash(user.password,password=password):
            wrapped_user = UserWrapper(user)
            login_user(wrapped_user)
            return redirect('/menu')
        else:
            flash('ユーザ名かパスワードが違います。')
            return redirect(url_for('login'))
    elif request.method == 'GET':
        return render_template('login.html', show_navbar=False)
    
@app.route('/logout',methods=['GET','POST'])
@login_required
def logout():
    logout_user()
    return redirect('/login')


#Flask --app main.menuapp run --debug で実行
