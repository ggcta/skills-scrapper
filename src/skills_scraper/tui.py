import sys
from skills_scraper.config import BASE_URL_PARTNERS, OUTPUT_FOLDER_NAME, DATA_FOLDER_NAME, WEBDRIVER_PROFILE_FOLDER_NAME
from skills_scraper.model.path import Path
from skills_scraper.model.paths import Paths
from skills_scraper.model.labs import Labs
from skills_scraper.model.course import Course
from skills_scraper.model.courses import Courses
from skills_scraper.services.browser import launch_browser


# Main class for the CloudSkillsBoost Automation Script
class CloudSkillsBoost:
    def __init__(self):
        self.paths_collection, self.courses_collection, self.labs_collection = self.load_data()
        self._driver = None

    @property
    def driver(self):
        """The signed-in browser, launched on first use and reused after that."""
        if self._driver is None:
            print("\n\033[35mLaunching the browser...\033[0m\n")
            self._driver = launch_browser(profile_folder=WEBDRIVER_PROFILE_FOLDER_NAME,
                                          headless=False)
        return self._driver

    def close(self):
        """Quit the browser if one was launched."""
        if self._driver is not None:
            self._driver.quit()
            self._driver = None

    @staticmethod
    def load_data():
        col_paths = Paths(name='Paths Collection')
        col_paths.load_json()

        col_courses = Courses(name='Courses Collection')
        col_courses.load_json()

        col_labs = Labs(name='Labs Collection')
        col_labs.load_json()

        return col_paths, col_courses, col_labs

    # Task Coordinator
    def tasks_coordinator(self, a_path_id=None, a_course_id=None) -> None:
        """
        Coordinate the tasks for a given path or course.

        :param a_path_id: Path ID.
        :param a_course_id: Course ID.
        """

        extract_transcript_task = False

        task_selection = True
        while task_selection:
            # Ask for what to do with the selected path id or course id.
            task_to_do = input("WHAT TASK YOU WANT TO GO WITH? (THIS IS A MUST): \n"
                               "\t\te. Extract Transcripts\n"
                               "\t\tb. Back\n"
                               "\t\tq. Quit\n"
                               "•PLEASE SELECT: ")

            # Set variables accordingly for each selection.
            if task_to_do.lower() == "e":
                extract_transcript_task = True
                task_selection = False
            elif task_to_do.lower() == "b":
                return
            elif task_to_do.lower() == "q":
                print("Got it. Bye.")
                sys.exit(0)
            else:
                print("Please select a valid choice: e or q to quit the program.")
                continue

        #  =======================================================================
        # If no path id, extract transcript for a certain course id only.
        if a_path_id is None and a_course_id:

            if a_course_id in self.courses_collection.collection:
                course_name = self.courses_collection.collection[a_course_id]
            else:
                # TODO: Use None for not existing course
                course_name = '(Unknown Course Yet)'

            # If the user wants to extract the transcript
            if extract_transcript_task:
                heading = f"{a_course_id} - {course_name.upper()}"
                print(f"\n\033[45m[{heading:^85}]\033[0m")
                course = Course(id=a_course_id, driver=self.driver)
                course.extract_transcript()
                # Save the course name to the collection
                # TODO: Save only those missing courses.
                self.courses_collection.collection[course.id] = course.name
                self.courses_collection.save_json()

        #  =======================================================================
        # A path is submitted, list all the courses in the path and let user select
        if a_path_id:
            path_data = Path(id=a_path_id, driver=self.driver)
            path_data.load_json()

            # If the path has no data yet
            # Load it from the web, save it
            # Add its courses to courses collection
            # Print out its courses to the screen and prompting to user
            if not path_data.courses:
                path_data.fetch_data()

                # Save the Path's details into files, JSON and MD
                path_data.save_json()
                path_data.save_markdown()

                # Add courses from this path to the courses collection
                for course in path_data.courses.values():
                    course_id = course['id']
                    course_name = course['name']
                    self.courses_collection.collection[course_id] = course_name

                # Save the course collection to file.
                self.courses_collection.save_json()

            # List all the courses in the path for the user to select
            path_data.courses_list()

            # TODO: Extract the logic below into a separated method.
            a_course_id = input("\nPLEASE SELECT A COURSE [id or A(ll) (e to exit back, q to quit)]: ")

            if a_course_id.lower() == "a" or a_course_id.lower() == "all":
                if extract_transcript_task:
                    for course in path_data.courses.values():
                        current_course_id: str = course['id']
                        current_course_name: str = course['name']

                        heading = f"{current_course_id} - {current_course_name.upper()}"
                        print(f"\n\033[45m[{heading:^85}]\033[0m")

                        course_instance = Course(id=current_course_id, name=current_course_name, driver=self.driver)
                        course_instance.extract_transcript()

                        # Save the course name to the collection
                        self.courses_collection.collection[course_instance.id] = course_instance.name
                        self.courses_collection.save_json()

                        print("(tasks_coordinator) The transcript has been extracted.\n")

            elif a_course_id.isdigit():
                if extract_transcript_task:
                    heading = f"{a_course_id} - {path_data.courses[a_course_id]['name'].upper()}"
                    print(f"\n\033[45m[{heading:^85}]\033[0m")

                    course_instance = Course(id=a_course_id, name=path_data.courses[a_course_id]['name'], driver=self.driver)
                    course_instance.extract_transcript()
                    # Save the course name to the collection
                    self.courses_collection.collection[course_instance.id] = course_instance.name
                    self.courses_collection.save_json()

            elif a_course_id.lower() == "e":
                print("\t[<< Going Back]\n")
                return

            elif a_course_id.lower() == "q":
                print("Got it. Bye.")
                sys.exit(0)

            else:
                print("You need to choose a course id or A(ll) or q to quit the program.")
                return

    # Interactive mode for the CloudSkillsBoost Automation Script
    # TODO: Command-line interface for the CloudSkillsBoost Automation Script
    def interactive_mode(self):
        """
        Interactive mode for the CloudSkillsBoost Automation Script.
        """

        running = True
        while running:
            #  ===================================================================
            # Gathers all the courses or path names and prompts the user for selection
            # Allows working with a path, courses, or both options via a user-friendly interface
            course_or_path = input("AVAILABLE OPTIONS:\n"
                                   "\t\t1. c: A COURSE ID\n"
                                   "\t\t2. p: A PATH ID\n"
                                   "\t\t3. l: SHOW ME A LIST\n"
                                   "\t\t5. g: GENERATE PROMPT\n"
                                   "\t\t6. h: FETCH ALL COURSES\n"
                                   "\t\t8. w: LAUNCH THE BROWSER\n"
                                   "\t\t9. d: DEBUG: RELOADING DATA\n"
                                   "\t\t0. q: QUIT\n"
                                   "•PLEASE SELECT: "
                                )

            #  ===================================================================
            if course_or_path.lower() == '0' or course_or_path.lower() == "q":
                print("Ya. Good day.")
                running = False

            elif course_or_path.lower() == "1" or course_or_path.lower() == "c":
                course_id = input(f"•{'COURSE ID: ':>15}")
                if not course_id.strip().isdigit():
                    print("[ERROR] INVALID OR MISSING COURSE ID. "
                          "PLEASE PROVIDE A VALID NUMERIC COURSE ID!")

                if self.courses_collection and course_id in self.courses_collection.collection:
                    course_title = self.courses_collection.collection[course_id]
                    print(f"•{'SELECTED: ':>15}\033[45m"
                          f"{course_id}: {course_title}"
                          f"\033[0m\n")

                # Proceed with the certain course only
                self.tasks_coordinator(a_course_id=course_id)

            #  ===================================================================
            elif course_or_path.lower() == "2" or course_or_path.lower() == "p":

                path_id = input(f"•{'PATH ID: ':>15}")
                if not path_id.strip().isdigit():
                    print("\n\033[33m[ERROR] INVALID OR MISSING PATH ID. "
                          "PLEASE PROVIDE A VALID NUMERIC PATH ID!\033[0m\n")
                    continue

                # Proceed with the certain path and course
                path_title = self.paths_collection.collection.get(path_id)
                if path_title:
                    print(f"•{'SELECTED: ':>15}\033[45m"
                          f"{path_id} - {path_title}"
                          f"\033[0m\n")
                else:
                    self.paths_collection.fetch_paths()
                    self.paths_collection.save_json()
                    path_title = self.paths_collection.collection.get(path_id)
                    if path_title:
                        print(f"•{'SELECTED: ':>15}\033[45m"
                              f"{path_id} - {path_title}"
                              f"\033[0m\n")
                    else:
                        print(f"\n"
                              f"\033[33mYOU PROVIDED A WRONG PATH ID, I BELIEVE: {path_id}\n"
                              "PLEASE RETRY WITH THE FOLLOWING LIST OF PATH:\033[0m\n")
                        self.paths_collection.print_list()
                        continue

                self.tasks_coordinator(a_path_id=path_id)

            #  ===================================================================
            elif course_or_path.lower() == "3" or course_or_path.lower() == "l":

                # If a path list is gathered successfully
                self.paths_collection.print_list()
                # Use the hidden menu to fetch path list instead
                # if paths_collection.collection:
                #     # Print out all the paths
                #     paths_collection.print_list()
                # else:
                #     paths_collection.fetch_paths()
                #     # Write the new path list to the file
                #     paths_collection.save_json()

                #     # Prompt user to select a path
                #     paths_collection.print_list()

                # Prompt user to select a path to proceed with
                path_id = input("\033[34m"
                                "\n"
                                "SELECT A PATH ID (e to exit back, q to quit): "
                                "\033[0m")

                if not path_id.strip().isdigit() and path_id.lower() != "q" and path_id.lower() != "e":
                    # If the user provided a wrong path id
                    print("\n\033[33m[ERROR] INVALID OR MISSING PATH ID. "
                          "PLEASE PROVIDE A VALID NUMERIC PATH ID!\033[0m\n")
                    continue

                # Ensure the user enter a correct path id which is a number
                if path_id.strip().isdigit() and path_id in self.paths_collection.collection:
                    path_title = self.paths_collection.collection[path_id]
                    print(f"Entering... \033[45m"
                          f"•--{path_id:>{len(path_id) + 1}}: {path_title.upper()}"
                          f"\033[0m\n")

                    # Proceed with the selected path id
                    self.tasks_coordinator(a_path_id=path_id)

                # If the user wants to go back
                elif path_id.lower() == "e":
                    print("[<< Going Back]\n")
                    continue

                # User can q at this stage if not wanting to continue
                elif path_id.lower() == "q":
                    print("Bye.")
                    sys.exit(0)

                else:
                    print("\n\033[33m[ERROR] INVALID OR MISSING PATH ID. "
                          "PLEASE PROVIDE A VALID NUMERIC PATH ID!\033[0m\n")
                    continue

            elif course_or_path.lower() == '5' or course_or_path.lower() == 'g':
                course_id = input(f"•{'COURSE ID: ':>15}")
                if not course_id.strip().isdigit():
                    print("ERROR: INVALID OR MISSING COURSE ID. "
                          "PLEASE PROVIDE A VALID NUMERIC COURSE ID!")
                    sys.exit(1)

                if self.courses_collection and course_id in self.courses_collection.collection:
                    course_title = self.courses_collection.collection[course_id]
                    print(f"•{'SELECTED: ':>15}\033[45m"
                          f"{course_id}: {course_title}"
                          f"\033[0m\n")
                    
                    course = Course(id=course_id, name=course_title)
                    course.generate_prompt()
                    print("Generating prompt completed. Going back...\n")

            elif course_or_path.lower() == '6' or course_or_path.lower() == 'h':
                # Fetch every course in the collection, one browser for all of them
                for course_id, course_name in self.courses_collection.collection.items():
                    heading = f"{course_id} - {course_name.upper()}"
                    print(f"\n\033[45m[{heading:<85}]\033[0m")
                    Course(id=course_id, driver=self.driver).extract_transcript()
                self.courses_collection.save_json()

            elif course_or_path.lower() == '9' or course_or_path.lower() == 'd':
                print(f"\n"
                      "\033[35mDEBUG: RELOADING THE COURSES LIST... in several minutes\033[0m\n")
                # Refresh Paths list
                if self.paths_collection.fetch_paths():
                    print("Paths List refreshed. Proceed with courses of each path.\n")
                    self.paths_collection.save_json()
                    self.paths_collection.write_md()
                else:
                    print("Paths List NOT refreshed. Proceed with courses of each path.\n")

                # Get all courses from all the paths
                for path_id, path_name in self.paths_collection.collection.items():
                    print(f"+|-• \033[35m[{path_id:>5} - {path_name:<72}]\033[0m")
                    path_data = Path(id=path_id, name=path_name, driver=self.driver)
                    path_data.fetch_data()
                    # Save the path data to the file: JSON
                    path_data.save_json()
                    # Save the path data to the file: MD
                    path_data.save_markdown()
                    # Add courses from this path to the courses collection
                    for course in path_data.courses.values():
                        course_id = course['id']
                        course_name = course['name']
                        self.courses_collection.collection[course_id] = course_name
                self.courses_collection.save_json()
                print("\n"
                      "\033[35mDEBUG: COURSES LIST RELOADED.\033[0m\n")

            elif course_or_path.lower() == '8' or course_or_path.lower() == 'w':
                # Launch the browser
                # Open the sign-in page in the shared browser so the profile keeps the session
                self.driver.get(BASE_URL_PARTNERS)
                print("\n\033[35mDEBUG: BROWSER LAUNCHED. Sign in there, then come back.\033[0m\n")

            else:
                print("\033[31m"
                      f"[INVALID CHOICE] {course_or_path}\n"
                      "PLEASE SELECT 1, 2, 3, 9 or q TO QUIT THE PROGRAM."
                      "\033[0m\n")
                continue


def main():
    """Entry point for the interactive (TUI) mode."""

    # Create the OUTPUT FOLDERS if they do not exist
    if not OUTPUT_FOLDER_NAME.exists():
        OUTPUT_FOLDER_NAME.mkdir(parents=True, exist_ok=True)
    
    # Create the DATA FOLDERS if they do not exist
    if not DATA_FOLDER_NAME.exists():
        DATA_FOLDER_NAME.mkdir(parents=True, exist_ok=True)

    # STARTING THE PROGRAM
    # https://talyian.github.io/ansicolors/
    # https://en.wikipedia.org/wiki/ANSI_escape_code
    app_title = "CloudSkillsBoost Automation Script"

    print()
    print("\033[45m"
          f"{app_title:^87}"
          "\033[0m")
    print()

    # Create an instance of CloudSkillsBoost and start interactive mode
    cloud_skills_boost = CloudSkillsBoost()
    try:
        cloud_skills_boost.interactive_mode()
    finally:
        cloud_skills_boost.close()

    sys.exit(0)


if __name__ == "__main__":
    main()

# TODO: Check if published_date is newer then update the path data
# TODO: Separated webdriver in tasks_coordinator()
# TODO: Check for existing course/lab md files.
# TODO: Make the collected data persistent, in another words, the application is stateful.
# TODO: Mark correct quiz(es) answers/options.
# TODO: Enable async to speed up the tasks
# TODO: LLM for transcript formatting, split into multiple semantic paragraphs.
# TODO: Non-login user.
# TODO: Remove <p> <p> <br/> from the transcript/text/description.
