#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sched.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <errno.h>

#define MAX_TASKS 32
#define MAX_CORES 8
#define WORKLOAD_SECONDS 60

/*
 * ============================================================
 * Task definition
 * ============================================================
 */
typedef struct {
    char name[16];
    int duty;
    double thermal_cost;

    int assigned_core;
    pid_t pid;
} Task;


/*
 * ============================================================
 * Physical-core definition
 * ============================================================
 *
 * thermal_cost:
 *     Empirical normalized thermal placement cost obtained
 *     from the single-core characterization.
 *
 * load:
 *     Scheduler-internal estimated thermal load.
 *
 * occupied:
 *     1 = a task has already been assigned to this core
 *     0 = core is still free
 *
 * IMPORTANT:
 * These values are NOT physical thermal coefficients.
 */
typedef struct {
    int core;
    double thermal_cost;
    double load;
    int occupied;
} Core;


/*
 * ============================================================
 * Measured core thermal placement costs
 * ============================================================
 *
 * Based on:
 *
 * Core  Avg Tctl  Normalized thermal cost
 *
 * 0     55.88     0.0000
 * 1     56.08     0.0551
 * 2     56.78     0.2479
 * 3     57.71     0.5041
 * 4     57.55     0.4601
 * 5     58.92     0.8375
 * 6     59.51     1.0000
 * 7     59.38     0.9642
 *
 * These represent empirical placement costs.
 */
static Core cores[MAX_CORES] = {

    {0, 0.0000, 0.0000, 0},
    {1, 0.0551, 0.0551, 0},
    {2, 0.2479, 0.2479, 0},
    {3, 0.5041, 0.5041, 0},
    {4, 0.4601, 0.4601, 0},
    {5, 0.8375, 0.8375, 0},
    {6, 1.0000, 1.0000, 0},
    {7, 0.9642, 0.9642, 0}
};


/*
 * ============================================================
 * Measured task thermal costs
 * ============================================================
 *
 * These are the measured average package/control-temperature
 * rises for the CPU duty-cycle workload.
 *
 * They are thermal-cost proxies, NOT CPU power values.
 */
static double get_thermal_cost(int duty)
{
    switch (duty) {

        case 25:
            return 4.288;

        case 50:
            return 9.464;

        case 75:
            return 11.087;

        case 100:
            return 13.317;

        default:

            fprintf(stderr,
                    "ERROR: Unsupported duty level: %d%%\n",
                    duty);

            exit(EXIT_FAILURE);
    }
}


/*
 * ============================================================
 * Sort tasks by decreasing thermal cost
 * ============================================================
 *
 * This follows the basic decreasing-cost ordering used by
 * the WFD-style assignment.
 */
static int compare_tasks(const void *a, const void *b)
{
    const Task *ta = (const Task *)a;
    const Task *tb = (const Task *)b;

    if (ta->thermal_cost < tb->thermal_cost)
        return 1;

    if (ta->thermal_cost > tb->thermal_cost)
        return -1;

    return 0;
}


/*
 * ============================================================
 * Select a physical core
 * ============================================================
 *
 * Policy:
 *
 * 1. If unused physical cores remain, choose the unused core
 *    with the lowest empirical thermal placement cost.
 *
 * 2. Once every physical core has one task, additional tasks
 *    are assigned to the currently lowest estimated load.
 *
 * This prevents two tasks from being placed on the same
 * physical core when there are enough free cores.
 */
static int select_core(Task *task)
{
    const double MAX_TASK_COST = 13.317;

    int best = -1;


    /*
     * --------------------------------------------------------
     * Phase 1:
     *
     * Use every physical core once before sharing cores.
     * --------------------------------------------------------
     */
    for (int c = 0; c < MAX_CORES; c++) {

        if (!cores[c].occupied) {

            if (best == -1 ||
                cores[c].thermal_cost <
                cores[best].thermal_cost) {

                best = c;
            }
        }
    }


    /*
     * --------------------------------------------------------
     * Phase 2:
     *
     * If every physical core is already occupied,
     * choose the currently lowest estimated load.
     * --------------------------------------------------------
     */
    if (best == -1) {

        best = 0;

        for (int c = 1; c < MAX_CORES; c++) {

            if (cores[c].load < cores[best].load) {
                best = c;
            }
        }
    }


    /*
     * Normalize task thermal cost.
     *
     * The largest measured task thermal cost is T4 = 13.317 C.
     *
     * This normalization is only for the scheduler's
     * dimensionless load calculation.
     */
    double normalized_task_cost =
        task->thermal_cost / MAX_TASK_COST;


    /*
     * Update scheduler load.
     */
    cores[best].load += normalized_task_cost;


    /*
     * Mark physical core as occupied.
     */
    cores[best].occupied = 1;


    return best;
}


/*
 * ============================================================
 * Launch one cpu_duty workload
 * ============================================================
 */
static pid_t launch_task(Task *task)
{
    pid_t pid = fork();


    /*
     * --------------------------------------------------------
     * Fork failed
     * --------------------------------------------------------
     */
    if (pid < 0) {

        perror("fork");

        return -1;
    }


    /*
     * --------------------------------------------------------
     * Child process
     * --------------------------------------------------------
     */
    if (pid == 0) {

        char cpu_arg[16];
        char duration_arg[16];
        char duty_arg[16];


        snprintf(cpu_arg,
                 sizeof(cpu_arg),
                 "%d",
                 task->assigned_core);


        snprintf(duration_arg,
                 sizeof(duration_arg),
                 "%d",
                 WORKLOAD_SECONDS);


        snprintf(duty_arg,
                 sizeof(duty_arg),
                 "%d",
                 task->duty);


        printf("Starting %-3s on CPU %d (%d%%)\n",
               task->name,
               task->assigned_core,
               task->duty);

        fflush(stdout);


        /*
         * cpu_duty arguments:
         *
         * ./cpu_duty <CPU> <seconds> <duty>
         */
        execl("./cpu_duty",
              "./cpu_duty",
              cpu_arg,
              duration_arg,
              duty_arg,
              (char *)NULL);


        /*
         * Only reached if execl() fails.
         */
        perror("execl ./cpu_duty");

        _exit(EXIT_FAILURE);
    }


    /*
     * Parent returns child's PID.
     */
    return pid;
}


/*
 * ============================================================
 * Main
 * ============================================================
 */
int main(void)
{
    Task tasks[MAX_TASKS];

    int num_tasks = 0;


    /*
     * --------------------------------------------------------
     * Read task configuration
     * --------------------------------------------------------
     */
    FILE *fp = fopen("twfd_tasks.txt", "r");


    if (!fp) {

        perror("twfd_tasks.txt");

        return EXIT_FAILURE;
    }


    while (num_tasks < MAX_TASKS &&
           fscanf(fp,
                  "%15s %d",
                  tasks[num_tasks].name,
                  &tasks[num_tasks].duty) == 2) {


        tasks[num_tasks].thermal_cost =
            get_thermal_cost(tasks[num_tasks].duty);


        tasks[num_tasks].assigned_core = -1;

        tasks[num_tasks].pid = -1;


        num_tasks++;
    }


    fclose(fp);


    if (num_tasks == 0) {

        fprintf(stderr,
                "ERROR: No tasks found in twfd_tasks.txt\n");

        return EXIT_FAILURE;
    }


    /*
     * --------------------------------------------------------
     * Sort tasks by decreasing thermal cost.
     * --------------------------------------------------------
     */
    qsort(tasks,
          num_tasks,
          sizeof(Task),
          compare_tasks);


    /*
     * --------------------------------------------------------
     * Print header.
     * --------------------------------------------------------
     */
    printf("\n");

    printf("AMD Runtime T-WFD\n");

    printf("=================\n\n");


    /*
     * --------------------------------------------------------
     * Print sorted task list.
     * --------------------------------------------------------
     */
    printf("Task order after thermal sorting:\n");


    for (int i = 0; i < num_tasks; i++) {

        printf("  %-3s duty=%3d%% thermal_cost=%7.3f C\n",
               tasks[i].name,
               tasks[i].duty,
               tasks[i].thermal_cost);
    }


    /*
     * --------------------------------------------------------
     * Perform T-WFD assignment.
     * --------------------------------------------------------
     */
    printf("\n");

    printf("T-WFD assignments:\n");


    for (int i = 0; i < num_tasks; i++) {

        int core = select_core(&tasks[i]);


        tasks[i].assigned_core = core;


        printf("  %-3s (%3d%%) -> Core %d   estimated_load=%7.4f\n",
               tasks[i].name,
               tasks[i].duty,
               core,
               cores[core].load);
    }


    /*
     * --------------------------------------------------------
     * Print final estimated loads.
     * --------------------------------------------------------
     */
    printf("\n");

    printf("Final estimated loads:\n");


    for (int c = 0; c < MAX_CORES; c++) {

        printf("  Core %d : %.4f\n",
               cores[c].core,
               cores[c].load);
    }


    /*
     * --------------------------------------------------------
     * Show actual mapping before execution.
     * --------------------------------------------------------
     */
    printf("\n");

    printf("Final task-to-CPU mapping:\n");


    for (int i = 0; i < num_tasks; i++) {

        printf("  %-3s -> CPU %d\n",
               tasks[i].name,
               tasks[i].assigned_core);
    }


    /*
     * --------------------------------------------------------
     * Give user time to prepare thermal logger.
     * --------------------------------------------------------
     */
    printf("\n");

    printf("Starting workloads in 3 seconds...\n");

    fflush(stdout);

    sleep(3);


    /*
     * --------------------------------------------------------
     * Launch all tasks.
     * --------------------------------------------------------
     */
    for (int i = 0; i < num_tasks; i++) {

        pid_t pid = launch_task(&tasks[i]);


        if (pid < 0) {

            fprintf(stderr,
                    "ERROR: Could not start task %s\n",
                    tasks[i].name);

            return EXIT_FAILURE;
        }


        tasks[i].pid = pid;
    }


    /*
     * --------------------------------------------------------
     * Wait for all tasks.
     * --------------------------------------------------------
     */
    for (int i = 0; i < num_tasks; i++) {

        int status;


        if (waitpid(tasks[i].pid,
                    &status,
                    0) < 0) {

            perror("waitpid");

            continue;
        }


        if (WIFEXITED(status)) {

            if (WEXITSTATUS(status) != 0) {

                fprintf(stderr,
                        "Task %s exited with status %d\n",
                        tasks[i].name,
                        WEXITSTATUS(status));
            }
        }
        else if (WIFSIGNALED(status)) {

            fprintf(stderr,
                    "Task %s terminated by signal %d\n",
                    tasks[i].name,
                    WTERMSIG(status));
        }
    }


    /*
     * --------------------------------------------------------
     * Finished.
     * --------------------------------------------------------
     */
    printf("\n");

    printf("All T-WFD workloads completed.\n");

    return EXIT_SUCCESS;
}
