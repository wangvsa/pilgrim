#!/usr/bin/env python
# encoding: utf-8
import pickle, os
from codegen import MPIFunction, MPIArgument
from instrument import filter_with_local_mpi_functions


def arg_type_strip(type_str):
    t = type_str.replace('*', '').replace('[', '').replace(']', '').replace(' ', '').replace('const', '')
    return t;

def is_mpi_object_arg(arg_type):
    # Do not include MPI_Status, MPI_Comm, and MPI_Offset
    mpi_objects = set([
        "MPI_Info", "MPI_Datatype", "MPI_File", "MPI_Win", "MPI_Request",
        "MPI_Group", "MPI_Op", "MPI_Message", "MPI_Comm"])
    if arg_type in mpi_objects:
        return True
    return False

def handle_special_apis(func):
    # These are handled in pilgrim_init_finalize.c
    if func.name == "MPI_Init" or func.name == "MPI_Init_thread" or func.name == "MPI_Finalize":
        return True

    # These are handled in pilgrim_init_pilgrim_wrappers_special.c
    ignored = ["MPI_Wait", "MPI_Waitany", "MPI_Waitsome", "MPI_Waitall", "MPI_Request_free", "MPI_Startall",
               "MPI_Test", "MPI_Testany", "MPI_Testsome", "MPI_Testall", "MPI_Pcontrol"]

    if func.name in ignored:
        return True

    return False


unique_types = set([])

def codegen_read_one_arg(func, i):

    def find_arg_idx(func, arg_name):
        for idx, arg in enumerate(func.arguments):
            if arg.name == arg_name:
                return idx
        return -1



    arg = func.arguments[i]

    unique_types.add(arg_type_strip(arg.type))

    lines = []
    if arg_type_strip(arg.type) == "int":
        lines.append('cs->arg_types[%d] = TYPE_INT;' %i)
    else:
        lines.append('cs->arg_types[%d] = TYPE_NON_MPI;' %i)
    lines.append('cs->arg_directions[%d] = DIRECTION_%s;' %(i, arg.direction))

    if 'void' in arg.type:
        lines.append('cs->arg_sizes[%d] = sizeof(int);' %i)
    elif 'MPI_Status' in arg.type:
        lines.append('cs->arg_sizes[%d] = sizeof(int)*2;' %i)
    elif 'MPI_Offset' in arg.type and '*' not in arg.type:  # keep separately
        pass
    elif is_mpi_object_arg(arg_type_strip(arg.type)):
        if "MPI_Comm" in arg.type :
            lines.append('cs->arg_sizes[%d] = sizeof(MPI_Comm)+sizeof(int);' %i)
        else:
            lines.append('cs->arg_sizes[%d] = sizeof(int);' %i)
        lines.append('cs->arg_types[%d] = TYPE_%s;' %(i, arg_type_strip(arg.type)))
    elif 'char*' in arg.type:
        if '**' not in arg.type and '[' not in arg.type:    # only consider one single string
            lines.append('cs->arg_sizes[%d] = strlen(buff+pos)+1;' %i)
    elif '*' in arg.type or '[' in arg.type:
        fixed_type = arg_type_strip(arg.type)
        if arg.length:
            if '*' in arg.length:   # n*3
                pass
            else:
                idx = find_arg_idx(func, arg.length)
                lines.append( 'length = *((int*) (cs->args[%d]));' %idx )
                lines.append( "cs->arg_sizes[%d] = length * sizeof(%s);" %(i, fixed_type))
        else:
            lines.append( "cs->arg_sizes[%d] = sizeof(%s);" %(i, fixed_type) )
    else:
        lines.append( "cs->arg_sizes[%d] = sizeof(%s);" %(i, arg.type) )

    lines.append('cs->args[%d] = calloc(cs->arg_sizes[%d], 1);' %(i,i))
    lines.append('memcpy(cs->args[%d], buff+pos, cs->arg_sizes[%d]);' %(i,i))
    lines.append('pos += cs->arg_sizes[%d];' %i)
    return lines


def generate_reader_file(funcs):
    f = open('../src/pilgrim_read_args.c', 'w')
    block = \
'''/* This file is generated automatically. Do not change. */
#include <stdlib.h>
#include <string.h>
#include <mpi.h>
#include "pilgrim.h"
#include "pilgrim_reader.h"
void read_record_args(int func_id, void* buff, CallSignature* cs) {
    int length, pos;
    size_t n;
    switch(func_id) {
'''
    f.write(block)

    for name in funcs:
        func = funcs[name]

        f.write('\t\tcase ID_%s:\n\t\t{\n' %name)

        if handle_special_apis(func):
            f.write('\t\t\tread_record_args_special(func_id, buff, cs);')
        else:
            f.write('\t\t\tcs->arg_count = %d;' %len(func.arguments))
            f.write('\n\t\t\tcs->arg_sizes = malloc(cs->arg_count * sizeof(int));')
            f.write('\n\t\t\tcs->arg_types = malloc(cs->arg_count * sizeof(int));')
            f.write('\n\t\t\tcs->arg_directions = malloc(cs->arg_count * sizeof(int));')
            f.write('\n\t\t\tcs->args = malloc(cs->arg_count * sizeof(void*));')
            f.write('\n\t\t\tpos = 0;')
            for i in range(len(func.arguments)):
                f.write('\n\t\t\t')
                lines = codegen_read_one_arg(func, i)
                f.write('\n\t\t\t'.join(lines))
        f.write('\n\t\t\tbreak;\n\t\t}\n')

    f.write('\t}\n}\n')
    f.close()

if __name__ == "__main__":
    f = open("./mpi_functions.pickle", 'r')
    funcs = pickle.load(f)
    f.close()

    funcs = filter_with_local_mpi_functions(funcs)

    generate_reader_file(funcs)
    print(unique_types)
    print(len(unique_types))