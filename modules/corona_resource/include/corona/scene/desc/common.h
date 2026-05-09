#pragma once

#include <ktm/type_vec.h>

#include <map>
#include <nlohmann/json.hpp>
#include <string>

namespace Corona::Resource::Scene {
/// @brief 参数包装器类型，使用 JSON 对象存储参数
using JsonWrapper = nlohmann::json;

/// @brief 哈希组合计算的魔数常量，基于黄金比例的整数形式
static constexpr std::uint64_t MAGIC_NUMBER = 0x9e3779b9ULL;

/**
 * @brief 多态模式枚举
 * @details 定义场景中多态对象的不同表示方式
 */
enum PolymorphicMode {
    EInstance = 0,
    ETopology = 1
};

/**
 * @brief 名称与ID的映射结构
 * @details 用于存储和管理名称字符串到唯一ID的映射关系
 */
struct NameID {
    /// @brief ID 类型定义
    using IDType = std::uint32_t;
    /// @brief 名称到ID的映射表类型
    using IDMap = std::map<std::string, IDType>;

    /// @brief 无效ID的常量值
    static constexpr IDType Invalid_ID = -1;

    /// @brief 名称字符串
    std::string name{""};
    /// @brief 对应的ID值
    IDType id{Invalid_ID};

    /**
     * @brief 检查名称ID是否有效
     * @return 如果ID不是无效值则返回true
     */
    bool valid() const;

    /**
     * @brief 从映射表中填充ID值
     * @param name2id_map 名称到ID的映射表
     * @details 根据名称在映射表中查找对应的ID，如果未找到则设置为Invalid_ID
     */
    void fill_id(const IDMap& name2id_map);
};

/**
 * @brief 属性标签枚举
 * @details 定义场景描述中使用的不同类型的属性标签
 */
enum class AttrTag {
    Number,       ///< 数值属性
    Albedo,       ///< 反照率属性
    Unbound,      ///< 未绑定属性
    Illumination  ///< 光照属性
};

/**
 * @brief 组合两个哈希值
 * @param h1 第一个哈希值
 * @param h2 第二个哈希值
 * @return 组合后的哈希值
 * @details 使用位运算和魔数常量将两个哈希值组合成一个新的哈希值
 */
inline std::uint64_t combine_hash(std::uint64_t h1, std::uint64_t h2) {
    return h1 ^ (h2 + MAGIC_NUMBER + (h1 << 6) + (h1 >> 2));
}

/**
 * @brief 将字符串转换为小写
 * @param str 输入字符串视图
 * @return 转换为小写后的字符串
 */
inline std::string to_lower(std::string_view str) {
    std::string result;
    result.reserve(str.size());
    for (char ch : str) {
        result.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
    }
    return result;
}

/**
 * @brief 将字符串转换为大写
 * @param str 输入字符串视图
 * @return 转换为大写后的字符串
 */
inline std::string to_upper(std::string_view str) {
    std::string result;
    result.reserve(str.size());
    for (char ch : str) {
        result.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(ch))));
    }
    return result;
}

struct MeasuredSS {
    const char* name{};
    ktm::fvec3 sigma_s;
    ktm::fvec3 sigma_a;
};

constexpr MeasuredSS SubsurfaceParameterTable[] = {
    // From "A Practical Model for Subsurface Light Transport"
    // Jensen, Marschner, Levoy, Hanrahan
    // Proc SIGGRAPH 2001
    {"Apple", ktm::fvec3(2.29, 2.39, 1.97), ktm::fvec3(0.0030, 0.0034, 0.046)},
    {"Chicken1", ktm::fvec3(0.15, 0.21, 0.38), ktm::fvec3(0.015, 0.077, 0.19)},
    {"Chicken2", ktm::fvec3(0.19, 0.25, 0.32), ktm::fvec3(0.018, 0.088, 0.20)},
    {"Cream", ktm::fvec3(7.38, 5.47, 3.15), ktm::fvec3(0.0002, 0.0028, 0.0163)},
    {"Ketchup", ktm::fvec3(0.18, 0.07, 0.03), ktm::fvec3(0.061, 0.97, 1.45)},
    {"Marble", ktm::fvec3(2.19, 2.62, 3.00), ktm::fvec3(0.0021, 0.0041, 0.0071)},
    {"Potato", ktm::fvec3(0.68, 0.70, 0.55), ktm::fvec3(0.0024, 0.0090, 0.12)},
    {"Skimmilk", ktm::fvec3(0.70, 1.22, 1.90), ktm::fvec3(0.0014, 0.0025, 0.0142)},
    {"Skin1", ktm::fvec3(0.74, 0.88, 1.01), ktm::fvec3(0.032, 0.17, 0.48)},
    {"Skin2", ktm::fvec3(1.09, 1.59, 1.79), ktm::fvec3(0.013, 0.070, 0.145)},
    {"Spectralon", ktm::fvec3(11.6, 20.4, 14.9), ktm::fvec3(0.00, 0.00, 0.00)},
    {"Wholemilk", ktm::fvec3(2.55, 3.21, 3.77), ktm::fvec3(0.0011, 0.0024, 0.014)},
    // From "Acquiring Scattering Properties of Participating Media by
    // Dilution",
    // Narasimhan, Gupta, Donner, Ramamoorthi, Nayar, Jensen
    // Proc SIGGRAPH 2006
    {"Lowfat Milk", ktm::fvec3(0.89187, 1.5136, 2.532), ktm::fvec3(0.002875, 0.00575, 0.0115)},
    {"Reduced Milk", ktm::fvec3(2.4858, 3.1669, 4.5214), ktm::fvec3(0.0025556, 0.0051111, 0.012778)},
    {"Regular Milk", ktm::fvec3(4.5513, 5.8294, 7.136), ktm::fvec3(0.0015333, 0.0046, 0.019933)},
    {"Espresso", ktm::fvec3(0.72378, 0.84557, 1.0247), ktm::fvec3(4.7984, 6.5751, 8.8493)},
    {"Mint Mocha Coffee", ktm::fvec3(0.31602, 0.38538, 0.48131), ktm::fvec3(3.772, 5.8228, 7.82)},
    {"Lowfat Soy Milk", ktm::fvec3(0.30576, 0.34233, 0.61664), ktm::fvec3(0.0014375, 0.0071875, 0.035937)},
    {"Regular Soy Milk", ktm::fvec3(0.59223, 0.73866, 1.4693), ktm::fvec3(0.0019167, 0.0095833, 0.065167)},
    {"Lowfat Chocolate Milk", ktm::fvec3(0.64925, 0.83916, 1.1057), ktm::fvec3(0.0115, 0.0368, 0.1564)},
    {"Regular Chocolate Milk", ktm::fvec3(1.4585, 2.1289, 2.9527), ktm::fvec3(0.010063, 0.043125, 0.14375)},
    {"Coke", ktm::fvec3(8.9053e-05, 8.372e-05, 0), ktm::fvec3(0.10014, 0.16503, 0.2468)},
    {"Pepsi", ktm::fvec3(6.1697e-05, 4.2564e-05, 0), ktm::fvec3(0.091641, 0.14158, 0.20729)},
    {"Sprite", ktm::fvec3(6.0306e-06, 6.4139e-06, 6.5504e-06), ktm::fvec3(0.001886, 0.0018308, 0.0020025)},
    {"Gatorade", ktm::fvec3(0.0024574, 0.003007, 0.0037325), ktm::fvec3(0.024794, 0.019289, 0.008878)},
    {"Chardonnay", ktm::fvec3(1.7982e-05, 1.3758e-05, 1.2023e-05), ktm::fvec3(0.010782, 0.011855, 0.023997)},
    {"White Zinfandel", ktm::fvec3(1.7501e-05, 1.9069e-05, 1.288e-05), ktm::fvec3(0.012072, 0.016184, 0.019843)},
    {"Merlot", ktm::fvec3(2.1129e-05, 0, 0), ktm::fvec3(0.11632, 0.25191, 0.29434)},
    {"Budweiser Beer", ktm::fvec3(2.4356e-05, 2.4079e-05, 1.0564e-05), ktm::fvec3(0.011492, 0.024911, 0.057786)},
    {"Coors Light Beer", ktm::fvec3(5.0922e-05, 4.301e-05, 0), ktm::fvec3(0.006164, 0.013984, 0.034983)},
    {"Clorox", ktm::fvec3(0.0024035, 0.0031373, 0.003991), ktm::fvec3(0.0033542, 0.014892, 0.026297)},
    {"Apple Juice", ktm::fvec3(0.00013612, 0.00015836, 0.000227), ktm::fvec3(0.012957, 0.023741, 0.052184)},
    {"Cranberry Juice", ktm::fvec3(0.00010402, 0.00011646, 7.8139e-05), ktm::fvec3(0.039437, 0.094223, 0.12426)},
    {"Grape Juice", ktm::fvec3(5.382e-05, 0, 0), ktm::fvec3(0.10404, 0.23958, 0.29325)},
    {"Ruby Grapefruit Juice", ktm::fvec3(0.011002, 0.010927, 0.011036), ktm::fvec3(0.085867, 0.18314, 0.25262)},
    {"White Grapefruit Juice", ktm::fvec3(0.22826, 0.23998, 0.32748), ktm::fvec3(0.0138, 0.018831, 0.056781)},
    {"Shampoo", ktm::fvec3(0.0007176, 0.0008303, 0.0009016), ktm::fvec3(0.014107, 0.045693, 0.061717)},
    {"Strawberry Shampoo", ktm::fvec3(0.00015671, 0.00015947, 1.518e-05), ktm::fvec3(0.01449, 0.05796, 0.075823)},
    {"Head & Shoulders Shampoo", ktm::fvec3(0.023805, 0.028804, 0.034306), ktm::fvec3(0.084621, 0.15688, 0.20365)},
    {"Lemon Tea Powder", ktm::fvec3(0.040224, 0.045264, 0.051081), ktm::fvec3(2.4288, 4.5757, 7.2127)},
    {"Orange Powder", ktm::fvec3(0.00015617, 0.00017482, 0.0001762), ktm::fvec3(0.001449, 0.003441, 0.007863)},
    {"Pink Lemonade Powder", ktm::fvec3(0.00012103, 0.00013073, 0.00012528), ktm::fvec3(0.001165, 0.002366, 0.003195)},
    {"Cappuccino Powder", ktm::fvec3(1.8436, 2.5851, 2.1662), ktm::fvec3(35.844, 49.547, 61.084)},
    {"Salt Powder", ktm::fvec3(0.027333, 0.032451, 0.031979), ktm::fvec3(0.28415, 0.3257, 0.34148)},
    {"Sugar Powder", ktm::fvec3(0.00022272, 0.00025513, 0.000271), ktm::fvec3(0.012638, 0.031051, 0.050124)},
    {"Suisse Mocha Powder", ktm::fvec3(2.7979, 3.5452, 4.3365), ktm::fvec3(17.502, 27.004, 35.433)},
    {"Pacific Ocean Surface Water", ktm::fvec3(0.0001764, 0.00032095, 0.00019617), ktm::fvec3(0.031845, 0.031324, 0.030147)}};

[[nodiscard]]
inline const MeasuredSS* find_medium(const std::string& name) {
    for (const auto& elm : SubsurfaceParameterTable) {
        if (elm.name == name) {
            return &elm;
        }
    }
    return &SubsurfaceParameterTable[0];
}

[[nodiscard]]
inline std::pair<ktm::fvec3, ktm::fvec3> get_sigma(const std::string& name) {
    const MeasuredSS* medium = find_medium(name);
    return {medium->sigma_s, medium->sigma_a};
}
}  // namespace Corona::Resource::Scene