import bpy
from bpy.types import NodeTree, Node, NodeSocket
from bpy.props import *
import os
import json
import arm.write_probes as write_probes
import arm.assets as assets
import arm.utils
import arm.nodes as nodes
import arm.log as log

def build_node_trees(active_worlds):
    s = bpy.data.filepath.split(os.path.sep)
    s.pop()
    fp = os.path.sep.join(s)
    os.chdir(fp)

    # Make sure Assets dir exists
    if not os.path.exists(arm.utils.build_dir() + '/compiled/Assets/materials'):
        os.makedirs(arm.utils.build_dir() + '/compiled/Assets/materials')
    
    # Export world nodes
    world_outputs = []
    for world in active_worlds:
        output = build_node_tree(world)
        world_outputs.append(output)
    return world_outputs

def build_node_tree(world):
    output = {}
    dat = {}
    output['material_datas'] = [dat]
    wname = arm.utils.safestr(world.name)
    dat['name'] = wname + '_material'
    context = {}
    dat['contexts'] = [context]
    context['name'] = 'world'
    context['bind_constants'] = []
    context['bind_textures'] = []
    
    bpy.data.worlds['Arm'].world_defs = ''
    
    # Traverse world node tree
    output_node = nodes.get_node_by_type(world.node_tree, 'OUTPUT_WORLD')
    if output_node != None:
        parse_world_output(world, output_node, context)
    
    # Clear to color if no texture or sky is provided
    wrd = bpy.data.worlds['Arm']
    if '_EnvSky' not in wrd.world_defs and '_EnvTex' not in wrd.world_defs:
        
        if '_EnvImg' not in wrd.world_defs:
            wrd.world_defs += '_EnvCol'
        
        # Irradiance json file name
        world.world_envtex_name = wname
        world.world_envtex_irr_name = wname
        write_probes.write_color_irradiance(wname, world.world_envtex_color)

    # Clouds enabled
    if wrd.generate_clouds:
        wrd.world_defs += '_EnvClouds'

    # Percentage closer soft shadows
    if wrd.generate_pcss_state == 'On':
        wrd.world_defs += '_PCSS'
        sdk_path = arm.utils.get_sdk_path()
        assets.add(sdk_path + 'armory/Assets/noise64.png')
        assets.add_embedded_data('noise64.png')

    # Screen-space ray-traced shadows
    if wrd.generate_ssrs:
        wrd.world_defs += '_SSRS'

    if wrd.generate_two_sided_area_lamp:
        wrd.world_defs += '_TwoSidedAreaLamp'

    # Alternative models
    if wrd.lighting_model == 'Cycles':
        wrd.world_defs += '_Cycles'

    # TODO: Lamp texture test..
    if wrd.generate_lamp_texture != '':
        bpy.data.worlds['Arm'].world_defs += '_LampColTex'

    if not wrd.generate_lamp_falloff:
        bpy.data.worlds['Arm'].world_defs += '_NoLampFalloff'

    voxelgi = False
    for cam in bpy.data.cameras:
        if cam.is_probe:
            wrd.world_defs += '_Probes'
        if cam.rp_shadowmap == 'None':
            wrd.world_defs += '_NoShadows'
            assets.add_khafile_def('arm_no_shadows')
        if cam.rp_voxelgi:
            voxelgi = True
        if cam.rp_dfrs:
            wrd.world_defs += '_DFRS'
            assets.add_khafile_def('arm_sdf')
        if cam.rp_dfao:
            wrd.world_defs += '_DFAO'
            assets.add_khafile_def('arm_sdf')
        if cam.rp_dfgi:
            wrd.world_defs += '_DFGI'
            assets.add_khafile_def('arm_sdf')
            wrd.world_defs += '_Rad' # Always do radiance for gi
            wrd.world_defs += '_Irr'

    if voxelgi:
        assets.add_khafile_def('arm_voxelgi')
        if wrd.voxelgi_revoxelize:
            assets.add_khafile_def('arm_voxelgi_revox')
        if wrd.voxelgi_multibounce:
            wrd.world_defs += '_VoxelGIMulti'
        wrd.world_defs += '_VoxelGI'
        wrd.world_defs += '_Rad' # Always do radiance for voxels
        wrd.world_defs += '_Irr'

    if arm.utils.get_gapi().startswith('direct3d'): # Flip Y axis in drawQuad command
        wrd.world_defs += '_InvY'

    # Area lamps
    for lamp in bpy.data.lamps:
        if lamp.type == 'AREA':
            wrd.world_defs += '_PolyLight'
            break

    # Data will be written after render path has been processed to gather all defines
    return output

def write_output(output):
    # Add datas to khafile
    dir_name = 'world'
    # Append world defs
    wrd = bpy.data.worlds['Arm']
    data_name = 'world' + wrd.world_defs + wrd.rp_defs
    
    # Reference correct shader context
    dat = output['material_datas'][0]
    dat['shader'] = data_name + '/' + data_name
    assets.add_shader2(dir_name, data_name)

    # Write material json
    path = arm.utils.build_dir() + '/compiled/Assets/materials/'
    asset_path = path + dat['name'] + '.arm'
    arm.utils.write_arm(asset_path, output)
    assets.add(asset_path)

def parse_world_output(world, node, context):
    if node.inputs[0].is_linked:
        surface_node = nodes.find_node_by_link(world.node_tree, node, node.inputs[0])
        parse_surface(world, surface_node, context)
    
def parse_surface(world, node, context):
    wrd = bpy.data.worlds['Arm']
    
    # Extract environment strength
    if node.type == 'BACKGROUND':
        
        # Append irradiance define
        if wrd.generate_irradiance:
            bpy.data.worlds['Arm'].world_defs += '_Irr'

        # Strength
        envmap_strength_const = {}
        envmap_strength_const['name'] = 'envmapStrength'
        envmap_strength_const['float'] = node.inputs[1].default_value
        # Always append for now, even though envmapStrength is not always needed
        context['bind_constants'].append(envmap_strength_const)
        
        if node.inputs[0].is_linked:
            color_node = nodes.find_node_by_link(world.node_tree, node, node.inputs[0])
            parse_color(world, color_node, context, envmap_strength_const)

        # Cache results
        world.world_envtex_color = node.inputs[0].default_value
        world.world_envtex_strength = envmap_strength_const['float']

def parse_color(world, node, context, envmap_strength_const):       
    wrd = bpy.data.worlds['Arm']

    # Env map included
    if node.type == 'TEX_ENVIRONMENT' and node.image != None:

        image = node.image
        filepath = image.filepath
        
        if image.packed_file == None and not os.path.isfile(arm.utils.asset_path(filepath)):
            log.warn(world.name + ' - unable to open ' + image.filepath)
            return

        tex = {}
        context['bind_textures'].append(tex)
        tex['name'] = 'envmap'
        tex['u_addressing'] = 'clamp'
        tex['v_addressing'] = 'clamp'

        # Reference image name
        tex['file'] = arm.utils.extract_filename(image.filepath)
        base = tex['file'].rsplit('.', 1)
        ext = base[1].lower()

        if ext == 'hdr':
            target_format = 'HDR'
        else:
            target_format = 'JPEG'
        do_convert = ext != 'hdr' and ext != 'jpg'
        if do_convert:
            if ext == 'exr':
                tex['file'] = base[0] + '.hdr'
                target_format = 'HDR'
            else:
                tex['file'] = base[0] + '.jpg'
                target_format = 'JPEG'

        if image.packed_file != None:
            # Extract packed data
            unpack_path = arm.utils.get_fp_build() + '/compiled/Assets/unpacked'
            if not os.path.exists(unpack_path):
                os.makedirs(unpack_path)
            unpack_filepath = unpack_path + '/' + tex['file']
            filepath = unpack_filepath

            if do_convert:
                if not os.path.isfile(unpack_filepath):
                    arm.utils.write_image(image, unpack_filepath, file_format=target_format)

            elif os.path.isfile(unpack_filepath) == False or os.path.getsize(unpack_filepath) != image.packed_file.size:
                with open(unpack_filepath, 'wb') as f:
                    f.write(image.packed_file.data)
            
            assets.add(unpack_filepath)
        else:
            if do_convert:
                converted_path = arm.utils.get_fp_build() + '/compiled/Assets/unpacked/' + tex['file']
                filepath = converted_path
                # TODO: delete cache when file changes
                if not os.path.isfile(converted_path):
                    arm.utils.write_image(image, converted_path, file_format=target_format)
                assets.add(converted_path)
            else:
                # Link image path to assets
                assets.add(arm.utils.asset_path(image.filepath))

        # Generate prefiltered envmaps
        world.world_envtex_name = tex['file']
        world.world_envtex_irr_name = tex['file'].rsplit('.', 1)[0]
        disable_hdr = target_format == 'JPEG'
        
        mip_count = world.world_envtex_num_mips
        mip_count = write_probes.write_probes(filepath, disable_hdr, mip_count, generate_radiance=wrd.generate_radiance)
        
        world.world_envtex_num_mips = mip_count
        
        # Append envtex define
        bpy.data.worlds['Arm'].world_defs += '_EnvTex'
        # Append LDR define
        if disable_hdr:
            bpy.data.worlds['Arm'].world_defs += '_EnvLDR'
        # Append radiance define
        if wrd.generate_irradiance and wrd.generate_radiance:
            bpy.data.worlds['Arm'].world_defs += '_Rad'

    # Static image background
    elif node.type == 'TEX_IMAGE':
        bpy.data.worlds['Arm'].world_defs += '_EnvImg'
        tex = {}
        context['bind_textures'].append(tex)
        tex['name'] = 'envmap'
        # No repeat for now
        tex['u_addressing'] = 'clamp'
        tex['v_addressing'] = 'clamp'
        
        image = node.image
        filepath = image.filepath

        if image.packed_file != None:
            # Extract packed data
            filepath = arm.utils.build_dir() + '/compiled/Assets/unpacked'
            unpack_path = arm.utils.get_fp() + filepath
            if not os.path.exists(unpack_path):
                os.makedirs(unpack_path)
            unpack_filepath = unpack_path + '/' + image.name
            if os.path.isfile(unpack_filepath) == False or os.path.getsize(unpack_filepath) != image.packed_file.size:
                with open(unpack_filepath, 'wb') as f:
                    f.write(image.packed_file.data)
            assets.add(unpack_filepath)
        else:
            # Link image path to assets
            assets.add(arm.utils.asset_path(image.filepath))

        # Reference image name
        tex['file'] = arm.utils.extract_filename(image.filepath)


    # Append sky define
    elif node.type == 'TEX_SKY':
        # Match to cycles
        envmap_strength_const['float'] *= 0.1
        
        bpy.data.worlds['Arm'].world_defs += '_EnvSky'
        # Append sky properties to material
        const = {}
        const['name'] = 'sunDirection'
        sun_direction = [node.sun_direction[0], node.sun_direction[1], node.sun_direction[2]]
        sun_direction[1] *= -1 # Fix Y orientation
        const['vec3'] = list(sun_direction)
        context['bind_constants'].append(const)
        
        world.world_envtex_sun_direction = sun_direction
        world.world_envtex_turbidity = node.turbidity
        world.world_envtex_ground_albedo = node.ground_albedo
        
        # Irradiance json file name
        wname = arm.utils.safestr(world.name)
        world.world_envtex_irr_name = wname
        write_probes.write_sky_irradiance(wname)

        # Radiance
        if wrd.generate_radiance_sky and wrd.generate_radiance and wrd.generate_irradiance:
            bpy.data.worlds['Arm'].world_defs += '_Rad'
            
            if wrd.generate_radiance_sky_type == 'Hosek':
                hosek_path = 'armory/Assets/hosek/'
            else:
                hosek_path = 'armory/Assets/hosek_fake/'

            sdk_path = arm.utils.get_sdk_path()
            # Use fake maps for now
            assets.add(sdk_path + hosek_path + 'hosek_radiance.hdr')
            for i in range(0, 8):
                assets.add(sdk_path + hosek_path + 'hosek_radiance_' + str(i) + '.hdr')
            
            world.world_envtex_name = 'hosek'
            world.world_envtex_num_mips = 8
