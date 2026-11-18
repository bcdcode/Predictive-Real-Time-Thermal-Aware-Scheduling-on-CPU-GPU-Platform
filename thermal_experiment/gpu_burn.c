#include <GL/glut.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static void display(void)
{
    glClear(GL_COLOR_BUFFER_BIT);

    glBegin(GL_TRIANGLES);

    for (int i = 0; i < 100000; i++) {
        float x = (float)(i % 1000) / 500.0f - 1.0f;
        float y = (float)(i / 1000) / 100.0f - 1.0f;

        glColor3f(
            (float)(i % 255) / 255.0f,
            (float)((i * 7) % 255) / 255.0f,
            (float)((i * 13) % 255) / 255.0f
        );

        glVertex2f(x, y);
        glVertex2f(x + 0.001f, y);
        glVertex2f(x, y + 0.001f);
    }

    glEnd();
    glutSwapBuffers();
}

static void idle(void)
{
    display();
}

int main(int argc, char **argv)
{
    int seconds = 60;

    if (argc > 1)
        seconds = atoi(argv[1]);

    glutInit(&argc, argv);
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB);
    glutInitWindowSize(640, 480);
    glutCreateWindow("GPU Thermal Characterization");

    glutDisplayFunc(display);
    glutIdleFunc(idle);

    time_t start = time(NULL);

    while (time(NULL) - start < seconds) {
        glutMainLoopEvent();
    }

    return 0;
}