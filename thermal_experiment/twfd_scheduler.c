#include <stdio.h>
#include <stdlib.h>

#define NUM_CORES 8

typedef struct {
    char name[8];
    int duty;
    double thermal_cost;
} Task;

typedef struct {
    int core;
    double thermal_load;
} Core;

int compare_tasks(const void *a, const void *b)
{
    const Task *ta = (const Task *)a;
    const Task *tb = (const Task *)b;

    if (ta->thermal_cost < tb->thermal_cost)
        return 1;

    if (ta->thermal_cost > tb->thermal_cost)
        return -1;

    return 0;
}

int main(void)
{
    /*
     * Empirical normalized thermal placement costs
     * obtained from the AMD platform measurements.
     */
    double core_cost[NUM_CORES] = {
        0.0000,
        0.0551,
        0.2479,
        0.5041,
        0.4601,
        0.8375,
        1.0000,
        0.9642
    };

    /*
     * Example workload set.
     *
     * T4 = highest thermal workload
     * T1 = lowest thermal workload
     */
    Task tasks[] = {
        {"T1", 25, 4.288},
        {"T2", 50, 9.464},
        {"T3", 75, 11.087},
        {"T4",100, 13.317},
        {"T1", 25, 4.288},
        {"T2", 50, 9.464},
        {"T3", 75, 11.087},
        {"T4",100, 13.317}
    };

    int num_tasks = sizeof(tasks) / sizeof(tasks[0]);

    Core cores[NUM_CORES];

    for (int i = 0; i < NUM_CORES; i++) {
        cores[i].core = i;
        cores[i].thermal_load = core_cost[i];
    }

    /*
     * T-WFD:
     *
     * 1. Sort tasks by decreasing thermal cost.
     * 2. For each task, select the currently lowest
     *    thermal-load core.
     */
    qsort(tasks, num_tasks, sizeof(Task), compare_tasks);

    printf("\nAMD T-WFD scheduling\n");
    printf("====================\n\n");

    printf("Task order after thermal sorting:\n");

    for (int i = 0; i < num_tasks; i++) {
        printf("  %s  duty=%3d%%  thermal_cost=%7.3f C\n",
               tasks[i].name,
               tasks[i].duty,
               tasks[i].thermal_cost);
    }

    printf("\nScheduling decisions:\n");

    for (int i = 0; i < num_tasks; i++) {

        int selected = 0;

        for (int c = 1; c < NUM_CORES; c++) {
            if (cores[c].thermal_load <
                cores[selected].thermal_load) {
                selected = c;
            }
        }

        printf("  %-2s (%3d%%) -> Core %d",
               tasks[i].name,
               tasks[i].duty,
               selected);

        cores[selected].thermal_load +=
            tasks[i].thermal_cost * 0.10 *
            (1.0 + core_cost[selected]);

        printf("   resulting_load=%.4f\n",
               cores[selected].thermal_load);
    }

    printf("\nFinal estimated core loads:\n");

    for (int i = 0; i < NUM_CORES; i++) {
        printf("  Core %d : %.4f\n",
               cores[i].core,
               cores[i].thermal_load);
    }

    return 0;
}
