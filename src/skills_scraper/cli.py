#!/usr/bin/env python3
import sys
import argparse
from skills_scraper.config.settings import WEBDRIVER_PROFILE_FOLDER_NAME, BASE_URL_PARTNERS

from skills_scraper.model.course import Course
from skills_scraper.model.path import Path
from skills_scraper.model.paths import Paths
from skills_scraper.model.courses import Courses
from skills_scraper.model.labs import Labs
from skills_scraper.services.launch_browser import launch_browser

def cmd_list(args):
    """Handle list command"""
    
    # Determine type
    if args.courses:
        target_class = Courses
        label = "courses"
    elif args.labs:
        target_class = Labs
        label = "labs"
    else:
        # Default to paths or if args.paths is set
        target_class = Paths
        label = "paths"

    # Reload if requested
    if args.reload:
        print(f"Reloading {label} list from remote...")
        collection = target_class()
        collection.load_json()
        
        # Ensure URL is up to date (specifically for Paths)
        if label == "paths":
            from skills_scraper.config.settings import BASE_URL_PATHS
            collection.url = BASE_URL_PATHS
            
        # Fetch list (Supports Path and Courses as they have fetch implemented)
        # Labs fetch might need implementation check, but we assume pattern holds or fails gracefully.
        try:
             # Dynamically call fetch method if exists or standard naming
             # Paths.fetch_paths, Courses.fetch_courses
             # We can use getattr
             method_name = f"fetch_{label}"
             fetch_method = getattr(collection, method_name, None)
             if fetch_method:
                 if fetch_method(force=True): # reload implies force
                     print(f"{label.capitalize()} list updated.")
                 else:
                     print(f"Failed to update {label} list.")
             else:
                 print(f"Reload not supported for {label}.")
        except Exception as e:
            print(f"Error reloading {label}: {e}")

    print(f"Listing all {label}...")
    
    # Instantiate and load (reload might have updated DB)
    collection = target_class()
    collection.load_json()
    
    # Check if empty (only for Paths/Courses mostly)
    if not collection.collection:
        print(f"No {label} found locally.")
        if label == 'paths' and not args.reload:
             print("Use 'list -r -p' to fetch paths list.")
        elif label == 'courses' and not args.reload:
             print("Use 'list -r -c' to fetch courses list.")
        else:
             return

    # Determine sort
    sort_by = 'id' if args.id else 'name'
    
    collection.print_list(sort_by=sort_by)

def cmd_fetch(args):
    """Handle fetch (scrape) command"""
    force = args.force
    no_md = args.no_md
    toc_only = args.toc
    no_transcript = args.no_transcript

    fetch_paths_ids = args.paths
    fetch_courses_ids = args.courses
    fetch_labs_ids = args.labs
    
    # Validation
    if not (fetch_paths_ids or fetch_courses_ids or fetch_labs_ids):
        print("Please specify items to fetch using -p <id>, -c <id>, or -l <id>.")
        return

    # --- Paths ---
    if fetch_paths_ids:
        print(f"\n--- Processing Paths: {fetch_paths_ids} ---")
        for pid in fetch_paths_ids:
            try:
                print(f"Processing Path {pid}...")
                p = Path(id=pid)
                # Load existing to see if we need to fetch? 
                # Fetch command implies scraping/updating.
                
                # Fetch data (scrapes remote)
                p.fetch_data()
                p.save_json() # Backs up to file and syncs to DB
                
                if not no_md:
                    p.save_markdown(toc_only=toc_only)
                    print(f"Path {pid} markdown updated.")
                print(f"Path {pid} updated.")
                
                # Original logic: update courses collection with courses found in path
                # This helps populate courses list without fetching all courses
                courses_collection = Courses()
                # We load just to be safe, but save_json will Upsert to DB which is fine
                
                # But Courses.collection is a dict {id: name}. 
                # We can't easily upsert to DB directly from here without loading Courses logic
                # Actually, Courses.save_json upserts the whole collection dict to DB.
                # So we should load it first to avoid overwriting with partial data if we use save_json.
                courses_collection.load_json()
                
                for course in p.courses.values():
                    c_id = course['id']
                    c_name = course['name']
                    courses_collection.collection[c_id] = c_name
                
                courses_collection.save_json()
                
            except Exception as e:
                print(f"Failed to fetch path {pid}: {e}")

    # --- Courses ---
    if fetch_courses_ids:
        print(f"\n--- Processing Courses: {fetch_courses_ids} ---")
        driver = None
        try:
             # Launch browser for authenticated access
             print("\n\033[35mLaunching browser for course extraction...\033[0m")
             driver = launch_browser(headless=False, browser="chrome", profile_folder=WEBDRIVER_PROFILE_FOLDER_NAME)
             
             for cid in fetch_courses_ids:
                try:
                    print(f"Processing Course {cid}...")
                    c = Course(id=cid, driver=driver)
                    # extract_transcript fetches page, extracts metadata, outline, modules, saves json/md.
                    c.extract_transcript(force=force, no_md=no_md, toc_only=toc_only, no_transcript=no_transcript)
                    print(f"Course {cid} updated.")
                except Exception as e:
                    print(f"Failed to fetch course {cid}: {e}")
        finally:
            if driver:
                print("Closing browser...")
                driver.quit()

    # --- Labs ---
    if fetch_labs_ids:
        print(f"\n--- Processing Labs: {fetch_labs_ids} ---")
        # Lab scraping logic is typically embedded in Course scraping (via extract_transcript -> process_lab).
        # We need to check if we can scrape a Lab directly.
        # Course.py has `process_lab` but it's part of course processing.
        # If we have a direct Lab URL or logic, we can implement it.
        # Currently, the original code didn't have standalone Lab scraping in `cmd_lab` (it didn't exist).
        # Use simple fallback: "Not supported directly, please fetch the parent course."
        print("Standalone Lab fetching is not yet fully supported (requires parent Course).")
        print("Please fetch the course containing this lab to update it.")

def cmd_search(args):
    """Handle search command"""
    from skills_scraper.services.database import Database
    
    query = args.query
    # Determine type from flags
    search_type = None
    if args.course:
        search_type = 'course'
    elif args.path:
        search_type = 'path'
    elif args.lab:
        search_type = 'lab'
        
    field = args.field
    
    db = Database()
    
    # Determine tables to search
    tables = []
    
    # Shortcuts for field search if query looks like specific type? No, stick to flags.
    
    if search_type:
        if search_type == 'course':
            tables.append('courses')
        elif search_type == 'path':
            tables.append('paths')
        elif search_type == 'lab':
            tables.append('labs')
    else:
        # Search all
        tables = ['paths', 'courses', 'labs']
    
    if not field:
        print(f"Searching for '{query}' in {tables}...")
    else:
        print(f"Searching for '{query}' in {tables} (field: {field})...")
    
    total_results = 0
    for table in tables:
        results = db.search(table, query, field)
        if results:
            print(f"\n--- {table} ({len(results)}) ---")
            for res in results:
                # Highlight ID and Name
                res_id = res.get('id', 'N/A')
                res_name = res.get('name', 'N/A')
                print(f"+|-• \033[35m[{res_id:>5} - {res_name:<72}]\033[0m")
            total_results += len(results)
            
    if total_results == 0:
        print("No results found.")

def cmd_browser(args):
    """Handle browser command"""
    print("\n\033[35mDEBUG: LAUNCHING THE BROWSER...\033[0m\n")
    
    profile = args.profile_folder if args.profile_folder else WEBDRIVER_PROFILE_FOLDER_NAME
    
    driver = launch_browser(profile_folder=profile, headless=False, browser="chrome")
    
    # Open the URL in the default web browser (PARTNERS page usually redirects to login if not logged in)
    driver.get(BASE_URL_PARTNERS)
    print("\n\033[35mDEBUG: BROWSER LAUNCHED.\033[0m")
    print("You can now log in. The script will keep running. Press Ctrl+C to exit and close browser.")
    
    try:
        # Keep the script running so the browser stays open
        # We can also just input() to wait
        input("Press Enter to close the browser and exit...")
    except KeyboardInterrupt:
        pass
    finally:
        print("Closing browser...")
        driver.quit()

def cmd_md(args):
    """Handle md command"""
    toc_only = args.toc
    no_transcript = args.no_transcript
    
    # Check if at least one type is provided
    if not (args.course or args.path or args.lab):
        print("Please specify at least one item type: --course, --path, or --lab.")
        return

    # Process Courses
    if args.course:
        course_ids = [cid.strip() for cid in args.course.split(',') if cid.strip()]
        for cid in course_ids:
            print(f"Generating markdown for Course {cid}...")
            course = Course(id=cid)
            course.load_json()
            if not course.name: # basic check if loaded
                 print(f"Course {cid} data not found. Please fetch/extract first.")
                 continue
            course.save_markdown(toc_only=toc_only, no_transcript=no_transcript)
            print(f"Markdown saved to {course._md_path}")

    # Process Paths
    if args.path:
        path_ids = [pid.strip() for pid in args.path.split(',') if pid.strip()]
        for pid in path_ids:
            print(f"Generating markdown for Path {pid}...")
            path = Path(id=pid)
            path.load_json()
            if not path.name:
                 print(f"Path {pid} data not found. Please fetch first.")
                 continue
            path.save_markdown(toc_only=toc_only)
            print(f"Markdown saved to {path._md_path}")

    # Process Labs
    if args.lab:
        lab_ids = [lid.strip() for lid in args.lab.split(',') if lid.strip()]
        for lid in lab_ids:
            print(f"Generating markdown for Lab {lid}...")
            lab = Lab(id=lid)
            lab.load_json()
             # Lab might not be fully implemented yet, but we support the structure
            if not lab.name:
                 print(f"Lab {lid} data not found.")
                 continue
            lab.save_markdown(toc_only=toc_only)
            print(f"Markdown saved to {lab._md_path}")

def main():
    parser = argparse.ArgumentParser(description="CloudSkillsBoost Scraper CLI")
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # List command
    parser_l = subparsers.add_parser('list', aliases=['l'], help='List all paths, courses, or labs')
    
    # Mutually exclusive group for type
    group_type = parser_l.add_mutually_exclusive_group()
    group_type.add_argument('--paths', '-p', action='store_true', help='List all paths (default)')
    group_type.add_argument('--courses', '-c', action='store_true', help='List all courses')
    group_type.add_argument('--labs', '-l', action='store_true', help='List all labs')
    
    # Reload flag
    parser_l.add_argument('--reload', '-r', action='store_true', help='Reload list from remote before listing')

    # Mutually exclusive group for sorting
    group_sort = parser_l.add_mutually_exclusive_group()
    group_sort.add_argument('--name', '-n', action='store_true', help='Sort by name (default)')
    group_sort.add_argument('--id', '-i', action='store_true', help='Sort by ID')
    
    parser_l.set_defaults(func=cmd_list)

    # Fetch command (Scrape)
    parser_f = subparsers.add_parser('fetch', aliases=['f'], help='Fetch (scrape) courses/paths/labs content')
    parser_f.add_argument('--paths', '-p', nargs='+', metavar='ID', help='Fetch specific path IDs')
    parser_f.add_argument('--courses', '-c', nargs='+', metavar='ID', help='Fetch specific course IDs')
    parser_f.add_argument('--labs', '-l', nargs='+', metavar='ID', help='Fetch specific lab IDs')
    
    # Flags from old course/path commands
    parser_f.add_argument('--force', '-f', action='store_true', help='Force re-extraction even if data exists')
    parser_f.add_argument('--no-md', action='store_true', help='Do not generate markdown file')
    parser_f.add_argument('--toc', '-t', action='store_true', help='Table of content only (structure only)')
    parser_f.add_argument('--no-transcript', action='store_true', help='Skip video transcripts (courses only)')
    
    parser_f.set_defaults(func=cmd_fetch)

    # Browser command
    parser_b = subparsers.add_parser('browser', aliases=['b', 'w'], help='Launch browser for manual login')
    parser_b.add_argument('--profile-folder', help='Specific webdriver profile folder', default=None)
    parser_b.set_defaults(func=cmd_browser)

    # MD command
    parser_m = subparsers.add_parser('md', help='Generate markdown output')
    parser_m.add_argument('--course', '-c', help='List of course IDs (comma-separated)', default=None)
    parser_m.add_argument('--lab', '-l', help='List of lab IDs (comma-separated)', default=None)
    parser_m.add_argument('--path', '-p', help='List of path IDs (comma-separated)', default=None)
    parser_m.add_argument('--toc', '-t', action='store_true', help='Table of content only (structure only)')
    parser_m.add_argument('--no-transcript', action='store_true', help='Skip video transcripts (courses only)')
    parser_m.set_defaults(func=cmd_md)

    # Search command
    parser_s = subparsers.add_parser('search', aliases=['s'], help='Search in database')
    parser_s.add_argument('query', help='Search query')
    parser_s.add_argument('--course', '-c', action='store_true', help='Search in courses')
    parser_s.add_argument('--path', '-p', action='store_true', help='Search in paths')
    parser_s.add_argument('--lab', '-l', action='store_true', help='Search in labs')
    parser_s.add_argument('--field', '-f', help='Limit search to specific field', default=None)
    parser_s.set_defaults(func=cmd_search)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute the selected command
    args.func(args)

if __name__ == "__main__":
    main()
