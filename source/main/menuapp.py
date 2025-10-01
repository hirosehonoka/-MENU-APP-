from flask import Flask,render_template,request,redirect,flash,url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.automap import automap_base
from sqlalchemy import  cast, BigInteger,literal,select,union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from flask_login import UserMixin,LoginManager,login_user,login_required,logout_user,current_user
from werkzeug.security import generate_password_hash,check_password_hash
import os
from collections import defaultdict
from dotenv import load_dotenv

app = Flask(__name__)

app.jinja_env.globals['getattr'] = getattr

app.config["SECRET_KEY"] = os.urandom(24)

load_dotenv() 
api_key = os.environ["PERPLEXITY_API_KEY"]

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
# RecipeNutrition = Base.classes.recipeNutritions
# Recipe = Base .classes.recipes
# ItemWeight = Base .classes .itemWeights
# NutritionalTarget = Base .classes.nutritionalTargets
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

@menu_bp.route('/createmenu', methods=['GET','POST'])
@login_required
def create_menu():
    # 1. ログインユーザ情報取得
    user = User.query.filter_by(userName=current_user.userName).first()
    if not user or not user.targets:
        flash("ユーザーターゲットが登録されていません")
        return redirect(url_for('index'))
    user_targets = user.targets # jsonb型。Pythonではdict想定
    
    # 2. NutritionalTargetからマッチングレコード探索
    # 年齢、性別、運動レベル
    targets_conditions = user_targets.copy()
    age = targets_conditions.get('年齢', None)
    sex = targets_conditions.get('性別', None)
    activity = targets_conditions.get('運動レベル', None)

    # 「75歳以上」かつ「運動レベル 高い」なら運動レベルを「ふつう」に
    activity_query = activity
    if age and ('75' in age and activity == '高い'):
        activity_query = 'ふつう'

    # SQLAlchemyによるjsonbフィールド完全一致 AND 年齢・性別・運動レベル条件
    nt = NutritionalTarget.query.filter(
        NutritionalTarget.targets['年齢'].astext == age,
        NutritionalTarget.targets['性別'].astext == sex,
        NutritionalTarget.targets['運動レベル'].astext == activity_query
    ).first()
    if nt is None:
        flash("栄養ターゲットが見つかりません")
        return redirect(url_for('index'))
    nutritional = nt.nutritional
    
    # 3. レシピ・食材・関連データ一式をIDごとにまとめて取得
    recipes = Recipe.query.all()
    recipe_nutritions = {r.recipeId: r.nutritions for r in RecipeNutrition.query.all()}
    recipe_items = {ri.recipeId: ri.items for ri in RecipeItem.query.all()}
    item_weights = {iw.itemName: iw.weights for iw in ItemWeight.query.all()}
    item_equals = {ie.itemName: ie.equals for ie in ItemEqual.query.all()}

    # 4. プロンプト文生成（prompt.py等に委譲することを推奨）
    # データのまとめ
    planning_data = {
        "nutritional_targets": nutritional,
        "recipes": [r.data for r in recipes],
        "recipe_nutritions": recipe_nutritions,
        "recipe_items": recipe_items,
        "item_weights": item_weights,
    }
    from prompt import generate_prompt  # 別ファイルでprompt生成
    solution_prompt = generate_prompt(planning_data)
    
    # 5. perplexityAPIで定式化
    import requests
    api_url = "https://api.perplexity.ai/v1/generate"  # 仮
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    api_resp = requests.post(api_url, headers=headers, json={"prompt": solution_prompt})
    api_resp.raise_for_status()
    optimization_input = api_resp.json().get('content')  # 期待される定式化テキスト

    # 6. Pyomo（+cbc）最適化
    from menu_planner import optimize_menu  # Pyomoモデル構築・解決部は分離推奨
    day_menus = optimize_menu(optimization_input)  # menu1, ..., menu7のJSON/dictが返る前提

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

    return redirect(url_for('/menu', menu_id=menu_obj.id))


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
def userupdate():
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
