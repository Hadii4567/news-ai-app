import sys
import os

# Add the project root to the Python path to allow importing 'app'
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

try:
    from app import app, automated_generate_article_task
except ImportError as e:
    print(f"Error importing from app.py: {e}")
    print("Make sure scheduler.py is in the root of your Flask project, alongside app.py.")
    print(f"Current sys.path: {sys.path}")
    sys.exit(1)

def run_task():
    """
    Runs the automated article generation task within the Flask app context.
    """
    with app.app_context():
        print("Scheduler script: Running automated_generate_article_task...")
        success = automated_generate_article_task()
        if success:
            print("Scheduler script: Task completed successfully.")
        else:
            print("Scheduler script: Task encountered an error.")

if __name__ == '__main__':
    print("Executing scheduler.py directly...")
    run_task()
    print("Scheduler.py execution finished.")
