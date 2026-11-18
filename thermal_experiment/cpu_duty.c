#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <sched.h>
#include <unistd.h>
#include <time.h>
#include <math.h>

static volatile double sink = 0.0;

static void busy_work(double seconds)
{
    struct timespec start, now;

    clock_gettime(CLOCK_MONOTONIC, &start);

    while (1) {
        double x = 1.001;
        double y = 0.999;

        for (int i = 0; i < 100000; i++) {
            x = sin(x) + cos(y);
            y = cos(y) + sin(x);
            x = sqrt(fabs(x) + 1.0);
            y = sqrt(fabs(y) + 1.0);
            sink += x * y;
        }

        clock_gettime(CLOCK_MONOTONIC, &now);

        double elapsed =
            (now.tv_sec - start.tv_sec) +
            (now.tv_nsec - start.tv_nsec) / 1e9;

        if (elapsed >= seconds)
            break;
    }
}

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr,
                "Usage: %s <cpu> <seconds> <duty_percent>\n",
                argv[0]);
        return 1;
    }

    int cpu = atoi(argv[1]);
    int seconds = atoi(argv[2]);
    int duty = atoi(argv[3]);

    if (duty < 1 || duty > 100) {
        fprintf(stderr, "Duty must be 1-100\n");
        return 1;
    }

    cpu_set_t set;

    CPU_ZERO(&set);
    CPU_SET(cpu, &set);

    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        perror("sched_setaffinity");
        return 1;
    }

    const double period = 0.100;
    const double busy = period * duty / 100.0;
    const double idle = period - busy;

    struct timespec start, now;

    clock_gettime(CLOCK_MONOTONIC, &start);

    while (1) {

        busy_work(busy);

        if (idle > 0)
            usleep((useconds_t)(idle * 1000000.0));

        clock_gettime(CLOCK_MONOTONIC, &now);

        double elapsed =
            (now.tv_sec - start.tv_sec) +
            (now.tv_nsec - start.tv_nsec) / 1e9;

        if (elapsed >= seconds)
            break;
    }

    fprintf(stderr,
            "CPU %d: %d%% duty, %d seconds, sink=%f\n",
            cpu, duty, seconds, sink);

    return 0;
}
