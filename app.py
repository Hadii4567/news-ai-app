import os
import datetime
import random # Added import random
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.routing import BaseConverter
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, DateTimeField, FileField, BooleanField, HiddenField
from wtforms.validators import DataRequired, Length, EqualTo, Optional, Regexp
from flask_wtf import FlaskForm
from slugify import slugify as pyslugify # Using a robust slugify library

# Load environment variables
load_dotenv()

# App Configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_default_secret_key') # CHANGE IN PRODUCTION
# Ensure the database URI uses an absolute path
db_path = os.path.join(app.root_path, "instance", "site.db")
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB max upload size

# Ensure instance folder and upload folder exist
if not os.path.exists(os.path.join(app.root_path, 'instance')):
    os.makedirs(os.path.join(app.root_path, 'instance'))
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Custom URL Converter for Slugs
class SlugConverter(BaseConverter):
    regex = r'[a-z0-9]+(?:-[a-z0-9]+)*' # Typical slug pattern

app.url_map.converters['slug'] = SlugConverter

# Database Setup
db = SQLAlchemy(app)

# Login Manager Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(250), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    pub_date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Can be null if AI generated
    author = db.relationship('User', backref=db.backref('articles', lazy=True))
    featured_image = db.Column(db.String(100), nullable=True)
    meta_title = db.Column(db.String(250), nullable=True)
    meta_description = db.Column(db.String(500), nullable=True)
    meta_keywords = db.Column(db.String(250), nullable=True)
    # Future fields: category, tags, status (draft, published)

    def __repr__(self):
        return f'<Article {self.title}>'

class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<SiteSetting {self.key}>'

# --- Forms ---
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=80)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class ArticleForm(FlaskForm):
    id = HiddenField('ID') # For editing existing articles
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    slug = StringField('Slug (URL friendly)', validators=[Optional(), Length(max=250), Regexp(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', message="Slug must be lowercase alphanumeric with hyphens.")])
    content = TextAreaField('Content', validators=[DataRequired()])
    pub_date = DateTimeField('Publication Date', format='%Y-%m-%d %H:%M:%S', default=datetime.datetime.utcnow, validators=[Optional()])
    featured_image = FileField('Featured Image (Optional)')
    delete_featured_image = BooleanField('Delete current featured image')
    meta_title = StringField('Meta Title (SEO)', validators=[Optional(), Length(max=250)])
    meta_description = TextAreaField('Meta Description (SEO)', validators=[Optional(), Length(max=500)])
    meta_keywords = StringField('Meta Keywords (SEO, comma-separated)', validators=[Optional(), Length(max=250)])
    submit = SubmitField('Save Article')

class SiteSettingsForm(FlaskForm):
    site_name = StringField('Site Name', validators=[DataRequired(), Length(max=100)])
    # site_logo = FileField('Site Logo (Optional)') # TODO: Implement logo upload
    # delete_logo = BooleanField('Delete current logo')
    submit = SubmitField('Save Settings')

class AdSettingsForm(FlaskForm):
    ad_space_sidebar = TextAreaField('Ad HTML/Script - Sidebar (Optional)')
    ad_space_article_bottom = TextAreaField('Ad HTML/Script - Below Article (Optional)')
    ad_space_header = TextAreaField('Ad HTML/Script - Header (Optional)')
    submit = SubmitField('Save Ad Settings')


# --- Helper Functions ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_site_config():
    if 'site_config' not in g:
        settings = SiteSetting.query.all()
        g.site_config = {setting.key: setting.value for setting in settings}
    return g.site_config

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# --- Context Processors ---
@app.context_processor
def inject_global_vars():
    return {
        'config': get_site_config(),
        'now': datetime.datetime.utcnow(), # Already provides current datetime
        'current_date_formatted': datetime.datetime.utcnow().strftime("%A, %B %d, %Y")
    }

# --- Routes ---
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 10 # Number of articles per page
    articles_pagination = Article.query.order_by(Article.pub_date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('index.html', articles=articles_pagination.items, pagination=articles_pagination)

@app.route('/article/<slug:article_slug>')
def view_article(article_slug):
    article = Article.query.filter_by(slug=article_slug).first_or_404()
    return render_template('article.html', article=article)

# --- Admin Routes ---
@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Logged in successfully!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('admin_dashboard'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('admin/login.html', form=form, title="Admin Login")

@app.route('/admin/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/admin')
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    articles = Article.query.order_by(Article.pub_date.desc()).limit(10).all()
    return render_template('admin/dashboard.html', articles=articles, title="Admin Dashboard")

@app.route('/admin/articles')
@login_required
def admin_manage_articles():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    articles_pagination = Article.query.order_by(Article.pub_date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin/manage_articles.html', articles=articles_pagination.items, pagination=articles_pagination, title="Manage Articles")


@app.route('/admin/article/create', methods=['GET'])
@login_required
def admin_create_article():
    form = ArticleForm()
    return render_template('admin/edit_article.html', form=form, title="Create Article", article=None)

@app.route('/admin/article/edit/<int:article_id>', methods=['GET'])
@login_required
def admin_edit_article(article_id):
    article = Article.query.get_or_404(article_id)
    form = ArticleForm(obj=article) # Pre-populate form
    if not form.pub_date.data and article.pub_date: # WTForms sometimes nulls DateTimeField on obj load
         form.pub_date.data = article.pub_date
    return render_template('admin/edit_article.html', form=form, title="Edit Article", article=article)

@app.route('/admin/article/save', methods=['POST'])
@login_required
def admin_save_article():
    form = ArticleForm()
    article_id = form.id.data

    if not form.slug.data and form.title.data: # Auto-generate slug if empty
        form.slug.data = pyslugify(form.title.data)

    # Validate slug uniqueness if it's new or changed
    if form.slug.data:
        existing_article_by_slug = Article.query.filter(Article.slug == form.slug.data)
        if article_id: # if editing
            existing_article_by_slug = existing_article_by_slug.filter(Article.id != int(article_id))
        existing_article_by_slug = existing_article_by_slug.first()
        if existing_article_by_slug:
            form.slug.errors.append("This slug is already in use. Please choose a different one.")

    if form.validate_on_submit() and not form.slug.errors:
        filename = None
        if form.featured_image.data and allowed_file(form.featured_image.data.filename):
            filename = secure_filename(form.featured_image.data.filename)
            # Ensure unique filename to prevent overwrites
            # base, ext = os.path.splitext(filename)
            # count = 1
            # temp_filename = filename
            # while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)):
            #     temp_filename = f"{base}_{count}{ext}"
            #     count += 1
            # filename = temp_filename
            # For simplicity now, just save it directly. Consider unique naming for production.
            form.featured_image.data.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        if article_id: # Editing existing article
            article = Article.query.get_or_404(int(article_id))
            article.title = form.title.data
            article.slug = form.slug.data
            article.content = form.content.data
            article.pub_date = form.pub_date.data or datetime.datetime.utcnow()
            article.meta_title = form.meta_title.data
            article.meta_description = form.meta_description.data
            article.meta_keywords = form.meta_keywords.data

            if form.delete_featured_image.data and article.featured_image:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], article.featured_image))
                except OSError:
                    pass # File might not exist, ignore
                article.featured_image = None

            if filename: # New image uploaded
                if article.featured_image: # Delete old if exists
                     try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], article.featured_image))
                     except OSError:
                        pass
                article.featured_image = filename

            flash('Article updated successfully!', 'success')
        else: # Creating new article
            new_article = Article(
                title=form.title.data,
                slug=form.slug.data,
                content=form.content.data,
                pub_date=form.pub_date.data or datetime.datetime.utcnow(),
                author_id=current_user.id,
                featured_image=filename,
                meta_title=form.meta_title.data,
                meta_description=form.meta_description.data,
                meta_keywords=form.meta_keywords.data
            )
            db.session.add(new_article)
            flash('Article created successfully!', 'success')

        db.session.commit()
        return redirect(url_for('admin_dashboard'))
    else:
        # If form validation fails, determine if it's create or edit mode for template
        article_instance = None
        if article_id:
            article_instance = Article.query.get(int(article_id))
        action_title = "Edit Article" if article_id else "Create Article"
        return render_template('admin/edit_article.html', form=form, title=action_title, article=article_instance)


@app.route('/admin/article/delete/<int:article_id>', methods=['POST'])
@login_required
def admin_delete_article(article_id):
    article = Article.query.get_or_404(article_id)
    if article.featured_image:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], article.featured_image))
        except OSError:
            pass # File might not exist
    db.session.delete(article)
    db.session.commit()
    flash('Article deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard')) # Or admin_manage_articles

@app.route('/admin/settings/site', methods=['GET', 'POST'])
@login_required
def admin_site_settings():
    form = SiteSettingsForm()
    if form.validate_on_submit():
        settings_to_update = {
            'SITE_NAME': form.site_name.data,
            # Add more settings here as needed, e.g., logo
        }
        for key, value in settings_to_update.items():
            setting = SiteSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                new_setting = SiteSetting(key=key, value=value)
                db.session.add(new_setting)
        db.session.commit()
        g.pop('site_config', None) # Clear cached config
        flash('Site settings updated!', 'success')
        return redirect(url_for('admin_site_settings'))

    # Populate form with current settings
    current_settings = get_site_config()
    form.site_name.data = current_settings.get('SITE_NAME', 'AI News Site')
    # Populate other form fields for logo etc. if they exist
    return render_template('admin/site_settings.html', form=form, title="Site Settings")


@app.route('/admin/settings/ads', methods=['GET', 'POST'])
@login_required
def admin_ad_settings():
    form = AdSettingsForm()
    if form.validate_on_submit():
        ads_to_update = {
            'AD_SPACE_SIDEBAR': form.ad_space_sidebar.data,
            'AD_SPACE_ARTICLE_BOTTOM': form.ad_space_article_bottom.data,
            'AD_SPACE_HEADER': form.ad_space_header.data,
        }
        for key, value in ads_to_update.items():
            setting = SiteSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                new_setting = SiteSetting(key=key, value=value)
                db.session.add(new_setting)
        db.session.commit()
        g.pop('site_config', None) # Clear cached config
        flash('Ad settings updated!', 'success')
        return redirect(url_for('admin_ad_settings'))

    current_settings = get_site_config()
    form.ad_space_sidebar.data = current_settings.get('AD_SPACE_SIDEBAR', '')
    form.ad_space_article_bottom.data = current_settings.get('AD_SPACE_ARTICLE_BOTTOM', '')
    form.ad_space_header.data = current_settings.get('AD_SPACE_HEADER', '')
    return render_template('admin/ad_settings.html', form=form, title="Ad Management")

@app.route('/admin/settings/seo', methods=['GET', 'POST'])
@login_required
def admin_seo_settings():
    # This is for global SEO settings, article specific SEO is in ArticleForm
    # Example: Global meta tags, Google Analytics ID, etc.
    # For now, this is a placeholder.
    flash("Global SEO settings page - TODO: Implement specific fields.", "info")
    return render_template('admin/seo_settings.html', title="Global SEO Settings")

# --- AI Content Generation (Placeholder) ---
def generate_ai_content_placeholder(keyword, num_paragraphs=3):
    """
    Generates placeholder AI content.
    In a real scenario, this would call an LLM or other AI service.
    """
    import random
    keyword_title = keyword.title()
    title_templates = [
        f"The Real Truth About {keyword_title}",
        f"Understanding {keyword_title}: A Deep Dive",
        f"{keyword_title}: What You Need to Know",
        f"Unpacking the Latest Trends in {keyword_title}",
        f"A Comprehensive Guide to {keyword_title}"
    ]
    title = random.choice(title_templates)

    intro_templates = [
        f"<p>The world of <strong>{keyword}</strong> is constantly evolving, presenting both new opportunities and unique challenges. This article aims to shed light on its current state and future prospects, offering readers a clear overview.</p>",
        f"<p>In recent times, <strong>{keyword}</strong> has captured significant attention. We will explore the key facets of this topic, providing a balanced perspective on its implications for various sectors.</p>",
        f"<p>Understanding the nuances of <strong>{keyword}</strong> is more critical than ever. This piece delves into its core components, examining the trends that are shaping its trajectory.</p>"
    ]

    body_paragraph_templates = [
        f"<p>One of the primary considerations when discussing <strong>{keyword}</strong> involves its impact on the broader technological landscape. Experts suggest that its development is accelerating at an unprecedented rate, leading to widespread adoption and integration. However, this rapid growth also brings questions about regulation and ethical use that need careful consideration.</p>",
        f"<p>From a practical standpoint, applications of <strong>{keyword}</strong> are becoming increasingly diverse. Industries are finding innovative ways to leverage its capabilities, leading to breakthroughs in efficiency and problem-solving. The ongoing research in this area promises even more exciting developments on the horizon, though challenges in implementation remain.</p>",
        "<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.</p>",
        "<p>Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit.</p>",
        f"<p>Further analysis of <strong>{keyword}</strong> reveals complex interdependencies with other emerging fields. The synergy created by these connections is a driving force behind much of the innovation seen today. It is essential for stakeholders to understand these dynamics to navigate the future effectively.</p>"
    ]

    conclusion_templates = [
        f"<p>In summary, while <strong>{keyword}</strong> offers immense potential, it's crucial to approach its development and deployment thoughtfully. Continued dialogue and research will be key to harnessing its benefits responsibly and mitigating potential risks. The journey ahead is complex but full of promise.</p>",
        f"<p>To conclude, the trajectory of <strong>{keyword}</strong> is one of dynamic change and significant impact. As we move forward, a multi-faceted approach involving innovation, ethical consideration, and collaborative efforts will be essential to navigate its evolving landscape successfully.</p>",
        f"<p>Ultimately, <strong>{keyword}</strong> stands as a testament to human ingenuity. Its future will be shaped by how effectively we can integrate its power while addressing the societal questions it raises. The path forward requires both optimism and caution.</p>"
    ]

    content_parts = [random.choice(intro_templates)]

    # Ensure num_paragraphs is at least 1 for intro, 1 for conclusion, so body needs num_paragraphs - 2
    num_body_paragraphs = max(0, num_paragraphs - 2) # Ensure it's not negative

    # Add body paragraphs
    if num_body_paragraphs > 0:
        # Use a mix of keyword-specific and generic lorem ipsum for variety if not enough specific templates
        selected_body_paragraphs = random.sample(body_paragraph_templates, min(num_body_paragraphs, len(body_paragraph_templates)))
        # If more paragraphs are needed than templates, fill with random lorem ipsum style
        while len(selected_body_paragraphs) < num_body_paragraphs:
            selected_body_paragraphs.append(random.choice(body_paragraph_templates[2:4])) # Pick from lorem ones

        for para in selected_body_paragraphs:
            content_parts.append(para)
    elif num_paragraphs == 1 and len(content_parts) > 0: # Only intro if 1 paragraph requested
        pass # Only intro is fine
    else: # If 0 or 1 paragraph requested, but intro already added. Or 2 para (intro+conclusion)
        pass


    content_parts.append(random.choice(conclusion_templates))
    content = "\n".join(content_parts)

    meta_description_templates = [
        f"An in-depth look at {keyword_title}. Discover its current trends, impacts, and what the future may hold for this dynamic field.",
        f"Explore the essentials of {keyword_title}. This article covers key aspects, challenges, and opportunities related to {keyword}.",
        f"Get the latest insights on {keyword_title}. Your guide to understanding the complexities and potential of {keyword}."
    ]

    return {
        "title": title,
        "content": content,
        "meta_description": random.choice(meta_description_templates),
        "meta_keywords": f"{keyword}, {keyword_title.lower()} trends, AI news, {keyword} analysis" # More varied keywords
    }

@app.route('/admin/generate-content', methods=['GET','POST'])
@login_required
def admin_run_content_generation():
    if request.method == 'POST':
        keyword = request.form.get('keyword')
        num_paragraphs = request.form.get('num_paragraphs', 3, type=int)

        if not keyword:
           flash("Keyword is required for manual generation.", "warning")
           return redirect(url_for('admin_generate_content_page')) # Redirect back to the form

        # Call AI generation logic
        ai_article_data = generate_ai_content_placeholder(keyword, num_paragraphs)

        if ai_article_data:
            slug = pyslugify(ai_article_data['title'])
            # Check for slug uniqueness
            counter = 1
            original_slug = slug
            while Article.query.filter_by(slug=slug).first():
                slug = f"{original_slug}-{counter}"
                counter += 1

            new_article = Article(
                title=ai_article_data['title'],
                slug=slug,
                content=ai_article_data['content'],
                pub_date=datetime.datetime.utcnow(),
                author_id=current_user.id, # Or a dedicated AI user ID
                meta_title=ai_article_data['title'], # Can be refined
                meta_description=ai_article_data.get('meta_description'),
                meta_keywords=ai_article_data.get('meta_keywords')
            )
            db.session.add(new_article)
            db.session.commit()
            flash(f"Placeholder article for '{keyword}' generated and saved successfully!", "success")
            return redirect(url_for('admin_edit_article', article_id=new_article.id)) # Redirect to edit page
        else:
           flash(f"Failed to generate placeholder article for '{keyword}'.", "danger")
           return redirect(url_for('admin_generate_content_page'))

    # For GET request, show the form page
    return render_template('admin/generate_content.html', title="Generate AI Content")

# --- SEO Routes ---
@app.route('/sitemap.xml')
def sitemap_xml():
    articles = Article.query.order_by(Article.pub_date.desc()).all()
    # In a real app, you'd also add static pages, category pages, etc.
    # For now, just articles.
    # Also, consider using Flask-Sitemap extension for more complex sites.

    # Get site URL root
    # In production, use request.url_root. For CLI generation, you might need to configure this.
    # For simplicity, we'll assume it's running on localhost or configured domain.
    # This might need adjustment based on deployment.
    # For now, this will work when the app is running.

    # A more robust way if behind a proxy or specific domain needed:
    # host_url = get_site_config().get('SITE_URL', request.url_root)
    # if host_url.endswith('/'):
    # host_url = host_url[:-1]

    # Simpler for now:
    host_url = request.url_root.rstrip('/')

    xml_content = render_template('sitemap.xml', articles=articles, host_url=host_url)
    response = app.response_class(xml_content, mimetype='application/xml')
    return response

# --- Automated Tasks ---
PREDEFINED_KEYWORDS = [
    "artificial intelligence breakthroughs", "future of machine learning", "quantum computing advances",
    "renewable energy innovations", "space exploration missions", "biotechnology trends",
    "cybersecurity threats and solutions", "the metaverse explained", "cryptocurrency market analysis",
    "electric vehicles future", "sustainable agriculture technology", "advances in robotics"
]

# Attempt to import Pytrends
try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False
    print("WARNING: pytrends library not found. Automated keyword generation will use predefined list.")


def get_trending_keyword():
    """
    Fetches a trending keyword using Pytrends.
    Falls back to predefined list if Pytrends is unavailable or fails.
    """
    import random
    if PYTRENDS_AVAILABLE:
        try:
            pytrends = TrendReq(hl='en-US', tz=360) # tz=360 is US timezone offset
            # Get daily trending searches. Parameter pn='united_states' for US.
            # For global, you might omit pn or use specific country codes.
            trending_df = pytrends.trending_searches(pn='united_states')

            if not trending_df.empty and 0 in trending_df.columns:
                # Take the top trend, or a random one from the top N
                # The dataframe contains trending search terms in the first column (index 0)
                top_trends = trending_df[0].tolist()
                if top_trends:
                    keyword = random.choice(top_trends)
                    print(f"Pytrends: Selected trending keyword: '{keyword}'")
                    return keyword
                else:
                    print("Pytrends: No trending keywords found in the dataframe.")
            else:
                print("Pytrends: Trending searches dataframe was empty or malformed.")
        except Exception as e:
            print(f"Pytrends: Error fetching trends: {e}. Falling back to predefined list.")
    else:
        print("Pytrends: Library not available. Falling back to predefined list.")

    # Fallback to predefined keywords
    keyword = random.choice(PREDEFINED_KEYWORDS)
    print(f"Fallback: Selected keyword from predefined list: '{keyword}'")
    return keyword


def automated_generate_article_task():
    """
    Headless task to generate and save an article.
    This function is intended to be called by a scheduler (e.g., cron job).
    It needs the app context to interact with the database.
    """
    print("Automated article generation task started...")
    try:
        # 1. Get a keyword
        keyword = get_trending_keyword()

        # 2. Generate content (using existing placeholder function)
        #    In a real scenario, this would be a more sophisticated AI call.
        ai_article_data = generate_ai_content_placeholder(keyword, num_paragraphs=random.randint(3, 5))
        print(f"Generated content for title: {ai_article_data['title']}")

        # 3. Get AI Author
        ai_author = User.query.filter_by(username='ai_author').first()
        if not ai_author:
            print("AI Author user ('ai_author') not found. Please create it first (e.g. via 'flask create-admin').")
            # Fallback to no author or admin for now, or handle error more gracefully
            author_id_to_set = None
        else:
            author_id_to_set = ai_author.id

        # 4. Save the article
        slug = pyslugify(ai_article_data['title'])
        counter = 1
        original_slug = slug
        while Article.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1

        new_article = Article(
            title=ai_article_data['title'],
            slug=slug,
            content=ai_article_data['content'],
            pub_date=datetime.datetime.utcnow(),
            author_id=author_id_to_set,
            meta_title=ai_article_data['title'],
            meta_description=ai_article_data.get('meta_description'),
            meta_keywords=ai_article_data.get('meta_keywords')
        )
        db.session.add(new_article)
        db.session.commit()
        print(f"Successfully saved new article: ID {new_article.id}, Slug: {new_article.slug}")
        return True
    except Exception as e:
        print(f"Error during automated article generation: {e}")
        # Potentially log to a file or a proper logging service
        db.session.rollback() # Rollback in case of error during commit
        return False


# --- CLI Commands ---
@app.cli.command("init-db")
def init_db_command():
    """Creates the database tables."""
    db.create_all()
    print("Initialized the database.")

@app.cli.command("create-admin")
def create_admin_command():
    """Creates the admin user."""
    if User.query.filter_by(username='admin').first():
        print("Admin user already exists.")
        return

    default_password = 'adminpassword' # Change this!
    admin_user = User(username='admin')
    admin_user.set_password(default_password)
    db.session.add(admin_user)
    print(f"Admin user 'admin' created with password '{default_password}'.")
    print("IMPORTANT: Change this password immediately.")

    # Create AI Author user if it doesn't exist
    ai_author = User.query.filter_by(username='ai_author').first()
    if not ai_author:
        ai_user = User(username='ai_author')
        # Set a very complex, random password that won't be used for login
        # Or, alternatively, modify User model to not require password for system users
        ai_user.set_password(os.urandom(16).hex())
        db.session.add(ai_user)
        print("User 'ai_author' created for automated content.")

    # Add default site name
    default_site_name = SiteSetting.query.filter_by(key='SITE_NAME').first()
    if not default_site_name:
        setting = SiteSetting(key='SITE_NAME', value='My AI News Site')
        db.session.add(setting)
        print("Default site name set.")

    db.session.commit()


if __name__ == '__main__':
    # Create tables if db doesn't exist or is empty (for development)
    with app.app_context():
        db.create_all() # Creates tables if they don't exist

        # Check if admin user exists, if not, guide to create one
        if not User.query.filter_by(username='admin').first():
            print("Admin user not found. Run 'flask create-admin' in your terminal to create one.")

        # Check for default site name
        if not SiteSetting.query.filter_by(key='SITE_NAME').first():
            setting = SiteSetting(key='SITE_NAME', value='My AI News Site')
            db.session.add(setting)
            db.session.commit()
            print("Default site name set.")

    app.run(debug=True) # debug=True is for development only
# To run:
# 1. export FLASK_APP=app.py
# 2. (Optional) export FLASK_ENV=development
# 3. flask init-db (if first time or db deleted)
# 4. flask create-admin (if first time)
# 5. flask run
#
# For slugify, added 'slugify' to requirements.txt (actually python-slugify)
# pip install Flask Flask-SQLAlchemy Flask-Login Werkzeug python-dotenv python-slugify Flask-WTF
# Make sure to create an 'instance' folder in the root directory for the SQLite DB.
# Make sure to create a 'static/uploads' folder for images.
# Add a .env file with SECRET_KEY=your_very_secret_flask_key
# e.g. in .env:
# SECRET_KEY='a_very_strong_random_secret_key_for_flask_sessions'
# DATABASE_URL='sqlite:///instance/site.db' # Optional, defaults to this anyway
#
# Note on DateTimeField in WTForms:
# It expects datetime objects. String conversion needs to be handled.
# Default format is '%Y-%m-%d %H:%M:%S'.
# When loading from DB for edit form, ensure it's a datetime object.
# Flask-SQLAlchemy usually handles this, but WTForms might need explicit format or pre-processing.
#
# Added templates:
# - admin/manage_articles.html
# - admin/site_settings.html
# - admin/ad_settings.html
# - admin/seo_settings.html (placeholder)
#
# Considerations for image uploads:
# - Unique filenames to prevent overwrites.
# - Resize/optimize images.
# - Security checks on uploaded files.
#
# Added python-slugify for robust slug generation.
# Added Flask-WTF for forms.
# Added .env file for environment variables.
# Added basic CLI commands for DB init and admin creation.
# Added pagination to index and admin manage articles.
#
# Slug uniqueness check added.
# Fixed DateTimeField issue for edit form.
# Added delete featured image functionality.
# Added SiteSetting model and basic site name customization.
# Added AdSetting model and basic ad snippet customization.
# Added placeholder for global SEO settings page.
# Added placeholder for manual content generation trigger.
# Added `g.site_config` for caching site settings per request.
# Added `inject_global_vars` context processor.
# Added basic file upload checks (allowed_file).
# Updated ArticleForm with slug regex and optional validation.
# Ensured instance and upload folders are created if they don't exist.
