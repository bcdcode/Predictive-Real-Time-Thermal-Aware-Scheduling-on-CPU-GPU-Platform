#define _GNU_SOURCE

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <sched.h>
#include <unistd.h>
#include <time.h>
#include <math.h>

static volatile double sink = 0.0;

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr,
                "Usage: %s <cpu> <seconds> <intensity>\n",
                argv[0]);
        return 1;
    }

    int cpu = atoi(argv[1]);
    int seconds = atoi(argv[2]);
    int intensity = atoi(argv[3]);

    if (intensity < 1 || intensity > 3) {
        fprintf(stderr, "Intensity must be 1, 2, or 3\n");
        return 1;
    }

    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);

    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        perror("sched_setaffinity");
        return 1;
    }

    /*
     * Three workload classes:
     *
     * 1 = light
     * 2 = medium
     * 3 = heavy
     */
    int operations;

    if (intensity == 1)
        operations = 250000;
    else if (intensity == 2)
        operations = 500000;
    else
        operations = 1000000;

    struct timespec start, now;
    clock_gettime(CLOCK_MONOTONIC, &start);

    uint64_t iterations = 0;

    while (1) {

        double x = 1.001;
        double y = 0.999;

        for (int i = 0; i < operations; i++) {
            x = sin(x) + cos(y);
            y = cos(y) + sin(x);
            x = sqrt(fabs(x) + 1.0);
            y = sqrt(fabs(y) + 1.0);

            sink += x * y;
        }

        iterations++;

        clock_gettime(CLOCK_MONOTONIC, &now);

        double elapsed =
            (now.tv_sec - start.tv_sec) +
            (now.tv_nsec - start.tv_nsec) / 1e9;

        if (elapsed >= seconds)
            break;
    }

    fprintf(stderr,
            "CPU %d: %.1f seconds, intensity %d, "
            "%d operations/iteration, %lu iterations, sink=%f\n",
            cpu,
            (double)seconds,
            intensity,
            operations,
            iterations,
            sink);

    return 0;
}
