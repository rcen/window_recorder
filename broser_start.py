import os
import random
from PIL import Image
import base64
from io import BytesIO
import markdown2
from datetime import datetime
import re

# Specify the folder containing your images
#image_folder = r"C:\Users\cr3881\OneDrive - Zebra Technologies\window_recorder\figs\tabs"

#inspirational_words = "Believe you can and you're halfway there. - Theodore Roosevelt"
#md_file_path = r"C:\Users\cr3881\OneDrive - Zebra Technologies\logseq-notes\journals\2024-07-05.md"
#md_folder = r"C:\Users\cr3881\OneDrive - Zebra Technologies\logseq-notes\journals"

def generate_inspirational_html(image_folder, md_folder, output_file="inspirational_image.html"):

    # Get a list of all image files in the folder
    image_files = [f for f in os.listdir(image_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]

    # Select a random image
    if image_files:
        random_image = random.choice(image_files)
        image_path = os.path.join(image_folder, random_image)
    else:
        print("No image files found in the specified folder.")
        exit()

    # Open the image and convert it to base64
    with Image.open(image_path) as img:
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

    # Todo list and inspirational words
    todo_list = [
        "1. Read a chapter of a book",
        "2. Work on a personal project"
    ]

    def get_latest_md_file(folder):
        def parse_date(filename):
            # Remove .md extension
            name = os.path.splitext(filename)[0]
            # Try to parse the date
            try:
                return datetime.strptime(name, '%Y-%m-%d')
            except ValueError:
                try:
                    return datetime.strptime(name, '%Y_%m_%d')
                except ValueError:
                    return None

        md_files = [f for f in os.listdir(folder) if f.endswith('.md')]
        valid_files = []

        for file in md_files:
            date = parse_date(file)
            if date:
                valid_files.append((file, date))

        if not valid_files:
            return None

        latest_file = max(valid_files, key=lambda x: x[1])
        return os.path.join(folder, latest_file[0])



    # Get the path of the latest .md file
    md_file_path = get_latest_md_file(md_folder)
    print(md_file_path)
    if not md_file_path:
        print("No valid .md files found in the specified folder.")
        exit()
    # Read the content of the .md file
    try:
        with open(md_file_path, 'r', encoding='utf-8') as md_file:
            md_content = md_file.read()
            md_content = markdown2.markdown(md_content)
    except FileNotFoundError:
        print(f"The file {md_file_path} was not found.")
        exit()
    except IOError:
        print(f"An error occurred while reading the file {md_file_path}.")
        exit()

    url = "file:///C:/Users/cr3881/OneDrive%20-%20Zebra%20Technologies/window_recorder/html/index.html"
    url2 = "https://jira.zebra.com/secure/RapidBoard.jspa?rapidView=4424&quickFilter=24811"
    url3 = "https://jira.zebra.com/secure/RapidBoard.jspa?rapidView=3891&selectedIssue=IK-706&quickFilter=20925#"

    # Generate HTML content
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Inspirational Image</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: Arial, sans-serif;
            }}
            .container {{
                position: relative;
                width: 100%;
                height: 100vh;
                overflow: hidden;
            }}
            .image {{
                width: 100%;
                height: 100%;
                object-fit: cover;
            }}
            .overlay {{
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                text-align: center;
                color: white;
                background-color: rgba(0, 0, 0, 0.6);
                padding: 20px;
                border-radius: 10px;
                max-height: 90vh; /* Ensure the overlay does not exceed the viewport height */
                max-width: 90vw; /* Ensure the overlay does not exceed the viewport width */
                overflow: auto; /* Add scroll bar if content exceeds the height */
            }}
            h2 {{
                margin-bottom: 20px;
            }}
            ul {{
                text-align: left;
                padding-left: 20px;
            }}
            .red-link {{
                color: red;
                text-decoration: none;
            }}
            .red-link:hover {{
                text-decoration: underline;
            }}
            .blue-link {{
                color: blue;
                text-decoration: none;
            }}
            .blue-link:hover {{
                text-decoration: underline;
            }}
            .green-link {{
                color: green;
                text-decoration: none;
            }}
            .green-link:hover {{
                text-decoration: underline;
            }}
            .yellow-link {{
                color: yellow;
                text-decoration: none;
            }}
            .yellow-link:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <img src="data:image/png;base64,{img_str}" alt="Inspirational Image" class="image">
            <div class="overlay">
                <h2>Today's Todo List</h2>
                <ul>
                    {"".join(f"<li>{item}</li>" for item in todo_list)}
                </ul>
                <pre>{md_content}</pre>
                <p><a href="{url}" class="red-link"> time tracker </a> </p>
                <p><a href="{url2}" class="green-link"> Zcode JIRA </a> </p>
                <p><a href="{url3}" class="yellow-link"> DCCV JIRA </a> </p>
            </div>
        </div>
    </body>
    </html>
    """

    # Write the HTML content to a file
    with open("inspirational_image.html", "w") as f:
        f.write(html_content)

    print("HTML file 'inspirational_image.html' has been generated successfully.")


# This allows the script to be run as a standalone program
# or imported as a module without automatically executing
if __name__ == "__main__":

    image_folder = r"C:\Users\cr3881\OneDrive - Zebra Technologies\window_recorder\figs\tabs"
    md_folder = r"C:\Users\cr3881\OneDrive - Zebra Technologies\logseq-notes\journals"
    result = generate_inspirational_html(image_folder, md_folder)
    print(result)