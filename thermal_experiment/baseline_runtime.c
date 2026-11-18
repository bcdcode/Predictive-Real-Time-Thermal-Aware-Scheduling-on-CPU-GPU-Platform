#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>

typedef struct {
    const char *name;
    int cpu;
    int duty;
} Task;

int main(void)
{
    Task tasks[] = {
        {"T4", 0, 100},
        {"T4", 1, 100},
        {"T3", 2,  75},
        {"T3", 3,  75},
        {"T2", 4,  50},
        {"T2", 5,  50},
        {"T1", 6,  25},
        {"T1", 7,  25}
    };

    int n = sizeof(tasks) / sizeof(tasks[0]);

    printf("Baseline thermal experiment\n");
    printf("===========================\n");

    pid_t pids[8];

    for (int i = 0; i < n; i++) {
        printf("%s -> CPU %d (%d%% duty)\n",
               tasks[i].name, tasks[i].cpu, tasks[i].duty);

        pid_t pid = fork();

        if (pid == 0) {
            char cpu_str[16];
            char duty_str[16];

            snprintf(cpu_str, sizeof(cpu_str), "%d", tasks[i].cpu);
            snprintf(duty_str, sizeof(duty_str), "%d", tasks[i].duty);

            execl("./cpu_duty",
                  "./cpu_duty",
                  cpu_str,
                  "60",
                  duty_str,
                  (char *)NULL);

            perror("execl");
            exit(1);
        }

        if (pid < 0) {
            perror("fork");
            return 1;
        }

        pids[i] = pid;
    }

    for (int i = 0; i < n; i++)
        waitpid(pids[i], NULL, 0);

    printf("All baseline workloads completed.\n");

    return 0;
}
